-- Keep sampled_at in the sort key so the admin page can plot a rolling 100-sample
-- chart per stage. TTL bounds retention at three days.
ALTER TABLE processing_eta_samples MODIFY TTL sampled_at + INTERVAL 3 DAY;
ALTER TABLE processing_eta_samples MODIFY COMMENT 'Rolling history of processing deadline estimates, newest 100 per stage shown on the admin page, retained for 3 days';
