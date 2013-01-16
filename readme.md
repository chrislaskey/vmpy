About ./vm.py
================================================================================
```vm.py``` is a python wrapper for the backup, adding, and cloning of
virtual machines running on KVM/QEMU/Libvirt host machines.

vm.py handles raw disk image backups (LVM logical volumes), and
simplifies management with virsh.

The three actions of vm.py are:

	```./vm.py backup```
		Backup a local VM to a disk image on the
		host machine or remote machine via SSH.

	```./vm.py import```
		Import a local or remote VM backup to the host
		machine. Import keeps essential values like UUID
		and network MAC address the same. Other values like
		the target logical volume are modifiable.
		See import --help for a full list of options.

	```./vm.py clone```
		Create a new VM based on a local VM backup image,
		remote VM backup image, or live VM. Cloning changes
		unique identifiers like VM UUID and network MAC address.
		Other VM values such as the VM name, networking
		information, persistent disk location, etc, are
		modifiable. See clone --help for full list of options.

See ```vm.py <action> --help``` for specific information and commands for each
action.

**Note:** this code is no longer developed. It was used in-house for a six month
period with great success. I decided to migrate from pure command-line vm
administration to GUI based with Proxmox for easier monitoring.

Changelog
================================================================================

Version 0.8.0
--------------------------------------------------------------------------------
Completed infrastructure rewrite. The "clone" action is tested and working.

Version 0.6.0
--------------------------------------------------------------------------------
Infrastructure rewrite in progress. The "import" action is tested and working.

Version 0.4.0
--------------------------------------------------------------------------------
Infrastructure rewrite in progress. Environmental information parsed and loaded.
The "backup" action is tested and working.

Version 0.3.0
--------------------------------------------------------------------------------
Infrastructure rewrite begun. Code simplified and documented.

Future
================================================================================
+ Refactor code into smaller, single-puporse subclasses.
+ Reimplement output/logging with Python stdlib logging module

License
================================================================================
This script is licensed under a 4 clause MIT license.
See LICENSE file for the complete license.
