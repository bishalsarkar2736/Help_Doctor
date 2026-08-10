from datetime import timedelta

# Appointment configuration
APPOINTMENT_DURATION_MINUTES = 20
APPOINTMENT_DURATION = timedelta(
    minutes=APPOINTMENT_DURATION_MINUTES
)

# Reminder configuration
#
# How far ahead of an appointment its reminder goes out, and therefore what
# "within the next day" means. Lives here rather than in the reminder task
# because TWO paths need it: the scheduled job, which reminds appointments as
# they pass through the band below this lead time, and appointment confirmation,
# which reminds immediately for an appointment already inside it.
#
# One definition on purpose. Two copies of "24 hours" would be free to drift, and
# a service that thought the lead time was 12 hours would silently hand
# appointments to a scheduler that never selects them.
REMINDER_LEAD_MINUTES = 24 * 60
