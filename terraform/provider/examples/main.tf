terraform {
  required_providers {
    cmo = { source = "godeskio/cmo" }
  }
}

# Admin password comes from CMO_ADMIN_PASSWORD; never commit it.
provider "cmo" {
  nodes = ["cache-1.internal:6379", "cache-2.internal:6379", "cache-3.internal:6379"]
  tls   = true
}

resource "cmo_api_key" "web_readonly" {
  scope  = "ro"
  prefix = "web:"
}

output "web_key_user" { value = cmo_api_key.web_readonly.id }
output "web_key_password" {
  value     = cmo_api_key.web_readonly.secret
  sensitive = true
}
