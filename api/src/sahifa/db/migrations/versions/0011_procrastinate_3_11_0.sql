-- Procrastinate 3.11.0 migration script
-- (procrastinate/sql/migrations/03.11.00_01_pre_fetch_job_skip_null_lock.sql), applied by
-- migration 0011. Kept as it was released. With the schema of migration 0004 it gives the
-- schema of Procrastinate 3.11.0 (tests/test_jobs.py checks both).
--
-- MIT License, see 0004_procrastinate_3_10_0.sql for the copyright notice and the text.

-- Migration: Make procrastinate_fetch_job_v2 skip the lock subquery for jobs without a lock
CREATE OR REPLACE FUNCTION procrastinate_fetch_job_v2(
    target_queue_names character varying[],
    p_worker_id bigint
)
    RETURNS procrastinate_jobs
    LANGUAGE plpgsql
AS $$
DECLARE
	found_jobs procrastinate_jobs;
BEGIN
    WITH candidate AS (
        SELECT jobs.*
            FROM procrastinate_jobs AS jobs
            WHERE
                -- reject the job if its lock has earlier or higher priority jobs.
                -- Jobs without a lock are accepted before the subquery is considered:
                -- keeping "jobs.lock IS NOT NULL" inside the subquery lets Postgres
                -- plan a nested loop that scans every other job for each NULL-lock job.
                (
                    jobs.lock IS NULL
                    OR NOT EXISTS (
                        SELECT 1
                            FROM procrastinate_jobs AS other_jobs
                            WHERE
                                other_jobs.lock = jobs.lock
                                AND (
                                    -- job with same lock is already running
                                    other_jobs.status = 'doing'
                                    OR
                                    -- job with same lock is waiting and has higher priority (or same priority but was queued first)
                                    (
                                        other_jobs.status = 'todo'
                                        AND (
                                            other_jobs.priority > jobs.priority
                                            OR (
                                            other_jobs.priority = jobs.priority
                                            AND other_jobs.id < jobs.id
                                            )
                                        )
                                    )
                                )
                    )
                )
                AND jobs.status = 'todo'
                AND (target_queue_names IS NULL OR jobs.queue_name = ANY( target_queue_names ))
                AND (jobs.scheduled_at IS NULL OR jobs.scheduled_at <= now())
            ORDER BY jobs.priority DESC, jobs.id ASC LIMIT 1
            FOR UPDATE OF jobs SKIP LOCKED
    )
    UPDATE procrastinate_jobs
        SET status = 'doing', worker_id = p_worker_id
        FROM candidate
        WHERE procrastinate_jobs.id = candidate.id
        RETURNING procrastinate_jobs.* INTO found_jobs;

 RETURN found_jobs;
END;
$$;
