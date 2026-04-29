# Monthly cost budget scoped to the Project=nexusf5 cost-allocation tag.
#
# Why a tag-scoped budget rather than account-wide:
#   The outlook account is mostly empty but not exclusively nexusf5. A
#   tag-scoped budget lets us alarm on this project's footprint without
#   coupling to whatever else lives in the account, and forces a real test
#   of cost-allocation tagging end-to-end (every nexusf5 resource carries
#   Project=nexusf5 via default_tags / explicit tags). If a resource isn't
#   tagged correctly, it falls outside the budget and can't trigger alerts
#   — that's a feature, not a bug, because it surfaces tagging gaps loudly.
#
# Threshold rationale:
#   50% — heads-up that something is running.
#   80% — second warning before the hard cap; iteration should stop here
#         until root cause is understood.
#   100% ACTUAL — confirmation that spend has reached cap; the per-run
#         timeout in tools/integration-wrapper.py is the real backstop, but
#         this catches leaks that the timeout missed.
#   100% FORECASTED — early warning that current spend rate will exceed cap
#         this month. Goes out before ACTUAL=100% and gives runway to react.
#
# Cost-allocation tags are not active by default; activate Project as a
# user-defined cost allocation tag in Billing once. AWS doesn't expose this
# via the standard providers (it's a one-time account-level setting), so
# the README documents it as a manual prerequisite alongside the marketplace
# subscription.
resource "aws_budgets_budget" "nexusf5_monthly" {
  name              = "nexusf5-monthly"
  budget_type       = "COST"
  limit_amount      = var.monthly_budget_usd
  limit_unit        = "USD"
  time_unit         = "MONTHLY"
  time_period_start = "2026-01-01_00:00"

  cost_filter {
    name   = "TagKeyValue"
    values = ["user:Project$nexusf5"]
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 50
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = [var.budget_alert_email]
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 80
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = [var.budget_alert_email]
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 100
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = [var.budget_alert_email]
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 100
    threshold_type             = "PERCENTAGE"
    notification_type          = "FORECASTED"
    subscriber_email_addresses = [var.budget_alert_email]
  }
}
