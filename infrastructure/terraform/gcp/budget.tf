# Budget alert. IMPORTANT: a budget only sends notifications; it does NOT stop or cap spending.
# The actual cost guards are: max_run_duration, the nightly stop schedule, the in-VM idle
# watchdog (cloud-init) and `scripts/destroy.sh`.
# Requires the Terraform identity to have Billing Account Costs Manager on the billing account.
resource "google_billing_budget" "monthly" {
  count           = var.billing_account_id != "" ? 1 : 0
  billing_account = var.billing_account_id
  display_name    = "${var.name}-monthly"

  budget_filter {
    projects = ["projects/${data.google_project.this.number}"]
    # count usage at full price so the alert also fires while the free-trial credit is paying
    credit_types_treatment = "EXCLUDE_ALL_CREDITS"
  }

  amount {
    specified_amount {
      units = tostring(var.budget_amount)
    }
  }

  threshold_rules { threshold_percent = 0.5 }
  threshold_rules { threshold_percent = 0.9 }
  threshold_rules { threshold_percent = 1.0 }
  threshold_rules {
    threshold_percent = 1.0
    spend_basis       = "FORECASTED_SPEND"
  }

  # Billing account admins/users always get e-mails. Optionally also notify an extra address.
  dynamic "all_updates_rule" {
    for_each = var.budget_alert_email != "" ? [1] : []
    content {
      monitoring_notification_channels = [google_monitoring_notification_channel.budget_email[0].id]
      disable_default_iam_recipients   = false
    }
  }

  depends_on = [google_project_service.apis]
}

resource "google_monitoring_notification_channel" "budget_email" {
  count        = var.billing_account_id != "" && var.budget_alert_email != "" ? 1 : 0
  display_name = "${var.name} budget e-mail"
  type         = "email"
  labels       = { email_address = var.budget_alert_email }
  depends_on   = [google_project_service.apis]
}
