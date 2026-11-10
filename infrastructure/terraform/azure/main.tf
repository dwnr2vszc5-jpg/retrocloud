# ALTERNATIVE PROVIDER - DRAFT. `terraform validate` passes; never applied.
# Mirrors the GCP layout: one Ubuntu 24.04 VM, NSG with SSH (admin only) + HTTPS + WebRTC UDP,
# managed data disk, nightly auto-shutdown, budget alert. Re-uses the GCP cloud-init with
# the metadata calls swapped (see docs/deployment.md, "Azure").
terraform {
  required_version = ">= 1.6"
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 5.0"
    }
  }
}

provider "azurerm" {
  features {}
  subscription_id = var.subscription_id
}

variable "subscription_id" { type = string }
variable "location" {
  type    = string
  default = "germanywestcentral"
}
variable "name" {
  type    = string
  default = "retrocloud"
}
variable "vm_size" {
  description = "Standard_D4as_v5 (4 vCPU / 16 GB) for the MVP."
  type        = string
  default     = "Standard_D4as_v5"
}
variable "spot" {
  type    = bool
  default = false
}
variable "admin_cidr" { type = string }
variable "ssh_public_key_path" {
  type    = string
  default = "~/.ssh/id_ed25519.pub"
}
variable "shutdown_time" {
  description = "Daily auto-shutdown, HHMM in var.timezone."
  type        = string
  default     = "0200"
}
variable "timezone" {
  type    = string
  default = "Turkey Standard Time"
}
variable "budget_amount" {
  type    = number
  default = 25
}
variable "budget_email" { type = string }
variable "budget_start" {
  description = "First day of the current month, e.g. 2026-11-01T00:00:00Z"
  type        = string
}

resource "azurerm_resource_group" "rg" {
  name     = "${var.name}-rg"
  location = var.location
}

resource "azurerm_virtual_network" "vnet" {
  name                = "${var.name}-vnet"
  address_space       = ["10.20.0.0/16"]
  location            = azurerm_resource_group.rg.location
  resource_group_name = azurerm_resource_group.rg.name
}

resource "azurerm_subnet" "subnet" {
  name                 = "workers"
  resource_group_name  = azurerm_resource_group.rg.name
  virtual_network_name = azurerm_virtual_network.vnet.name
  address_prefixes     = ["10.20.1.0/24"]
}

resource "azurerm_network_security_group" "nsg" {
  name                = "${var.name}-nsg"
  location            = azurerm_resource_group.rg.location
  resource_group_name = azurerm_resource_group.rg.name

  security_rule {
    name                       = "ssh-admin"
    priority                   = 100
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = "22"
    source_address_prefix      = var.admin_cidr
    destination_address_prefix = "*"
  }
  security_rule {
    name                       = "https"
    priority                   = 110
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_ranges    = ["80", "443"]
    source_address_prefix      = "*"
    destination_address_prefix = "*"
  }
  security_rule {
    name                       = "webrtc-udp"
    priority                   = 120
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "Udp"
    source_port_range          = "*"
    destination_port_range     = "50000-50100"
    source_address_prefix      = "*"
    destination_address_prefix = "*"
  }
}

# Standard SKU public IPs are static and billed (~$3.6/month) even while the VM is deallocated.
resource "azurerm_public_ip" "ip" {
  name                = "${var.name}-ip"
  location            = azurerm_resource_group.rg.location
  resource_group_name = azurerm_resource_group.rg.name
  allocation_method   = "Static"
  sku                 = "Standard"
}

resource "azurerm_network_interface" "nic" {
  name                = "${var.name}-nic"
  location            = azurerm_resource_group.rg.location
  resource_group_name = azurerm_resource_group.rg.name
  ip_configuration {
    name                          = "primary"
    subnet_id                     = azurerm_subnet.subnet.id
    private_ip_address_allocation = "Dynamic"
    public_ip_address_id          = azurerm_public_ip.ip.id
  }
}

resource "azurerm_network_interface_security_group_association" "nsg" {
  network_interface_id      = azurerm_network_interface.nic.id
  network_security_group_id = azurerm_network_security_group.nsg.id
}

resource "azurerm_linux_virtual_machine" "worker" {
  name                            = "${var.name}-worker-1"
  location                        = azurerm_resource_group.rg.location
  resource_group_name             = azurerm_resource_group.rg.name
  size                            = var.vm_size
  admin_username                  = "rcadmin"
  disable_password_authentication = true
  network_interface_ids           = [azurerm_network_interface.nic.id]
  priority                        = var.spot ? "Spot" : "Regular"
  eviction_policy                 = var.spot ? "Deallocate" : null

  admin_ssh_key {
    username   = "rcadmin"
    public_key = file(pathexpand(var.ssh_public_key_path))
  }

  os_disk {
    caching              = "ReadWrite"
    storage_account_type = "StandardSSD_LRS"
    disk_size_gb         = 30
  }

  source_image_reference {
    publisher = "Canonical"
    offer     = "ubuntu-24_04-lts"
    sku       = "server"
    version   = "latest"
  }
}

resource "azurerm_managed_disk" "data" {
  name                 = "${var.name}-data"
  location             = azurerm_resource_group.rg.location
  resource_group_name  = azurerm_resource_group.rg.name
  storage_account_type = "StandardSSD_LRS"
  create_option        = "Empty"
  disk_size_gb         = 10
}

resource "azurerm_virtual_machine_data_disk_attachment" "data" {
  managed_disk_id    = azurerm_managed_disk.data.id
  virtual_machine_id = azurerm_linux_virtual_machine.worker.id
  lun                = 0
  caching            = "ReadWrite"
}

# Deallocates the VM daily. Like GCP budgets, Azure budgets only alert.
resource "azurerm_dev_test_global_vm_shutdown_schedule" "nightly" {
  virtual_machine_id    = azurerm_linux_virtual_machine.worker.id
  location              = azurerm_resource_group.rg.location
  enabled               = true
  daily_recurrence_time = var.shutdown_time
  timezone              = var.timezone
  notification_settings {
    enabled = false
  }
}

resource "azurerm_consumption_budget_resource_group" "monthly" {
  name              = "${var.name}-monthly"
  resource_group_id = azurerm_resource_group.rg.id
  amount            = var.budget_amount
  time_grain        = "Monthly"
  time_period {
    start_date = var.budget_start
  }
  notification {
    enabled        = true
    threshold      = 80
    operator       = "GreaterThan"
    contact_emails = [var.budget_email]
  }
  notification {
    enabled        = true
    threshold      = 100
    operator       = "GreaterThan"
    threshold_type = "Forecasted"
    contact_emails = [var.budget_email]
  }
}

output "public_ip" { value = azurerm_public_ip.ip.ip_address }
