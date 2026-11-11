# frozen_string_literal: true

# Initializer that zone-jobs.py mounts in the OpenProject worker. GoodJob 4.19.2 does not run a cron time that
# passed while the worker was stopped, so the sync jobs run often.
Rails.application.config.after_initialize do
  cron = Rails.application.config.good_job.cron
  # The user sync copies the admin flag and the lock status from LDAP. It runs each minute instead of at 23:30.
  # Each run writes the status column of each LDAP user once.
  cron[:"Ldap::SynchronizationJob"] = cron[:"Ldap::SynchronizationJob"].merge(cron: "* * * * *")

  # openDesk users sign in through OIDC, so OpenProject creates them without the LDAP connection and the user sync
  # skips them. The admin flag then changes only at the next login. The sync therefore also takes each OIDC user
  # without a connection, and its update links the user to the connection. A user outside the connection filter,
  # for example without the projects flag, gets the locked status.
  Ldap::SynchronizeUsersService.prepend(Module.new do
    private

    def applicable_users
      return super if logins.present?

      User.where(ldap_auth_source_id: ldap.id)
        .or(User.where(ldap_auth_source_id: nil, id: UserAuthProviderLink.select(:user_id)))
    end
  end)

  # At start, the worker enqueues the most recent missed time of each cron entry. An entry that never ran also
  # runs, so a new zone does its first sync and cleanup at once. The unique cron key and time stop a second copy.
  if GoodJob::CLI.within_exe?
    GoodJob::CronEntry.all.each do |entry|
      next unless entry.enabled?

      missed = entry.send(:fugit).previous_time.to_t
      last = entry.last_job_at
      next if last && last >= missed

      entry.enqueue(missed)
      Rails.logger.info { "[hoover cron] enqueued #{entry.key} for #{missed.utc.iso8601}" }
    rescue StandardError => e
      Rails.logger.error { "[hoover cron] #{entry.key}: #{e.message}" }
    end
  end
end
