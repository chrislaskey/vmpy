#!/usr/bin/env python

'''
Information
================================================================================

@author Chris Laskey
@contact chrislaskey.com
@contact github.com/chrislaskey
@created 2012.05.01
@updated 2012.08.01
@version 1.8.11

For code commentary see README.md file.
For license information see LICENSE.txt file.

================================================================================
'''

# ==============================================================================
# Imports
# ==============================================================================
import argparse
import json
import os
import pdb
import pwd
import random
import subprocess
import sys
import traceback
import textwrap
import xml.etree.ElementTree as ElementTree

from datetime import datetime

# ==============================================================================
# Decorators
# ==============================================================================
def sys_exit(func):
    def wrapper(self, *args, **named_args):
        try:
            # Set modifiable variables.
            self.pid_file = './vmpy.pid'
            self.error_file = './vmpy-error-<datetime>.json'
            self.log_file = './vmpy-log.json'

            # Add status variables
            self.status = {}
            self.status['command'] = ' '.join(sys.argv)
            self.status['command_history'] = []
            self.status['time_start'] = str(datetime.now())
            self.status['user'] = pwd.getpwuid(os.getuid())[0]

            # Create pseudo-PID file
            self._output('Creating PID file.', 2)
            self._set_pid_file()

            # Execute function
            success = True
            return func(self, *args, **named_args)
        except BaseException, e:
            # Treat every exception as an error except for "sys.exit(0)"
            if hasattr(e, 'code') and e.code == 0:
                # Set exit status variables
                self.status['time_end'] = str(datetime.now())
                self.status['exit'] = 'Success'
            else:
                # Set exit status variables
                success = False
                tb = traceback.format_exc()
                self.status['time_end'] = str(datetime.now())
                self.status['exit'] = 'Fatal Error | {0}'.format(str(e))
                self.status['traceback'] = '{0}'.format(tb)

                # Try to log complete status to error log
                try:
                    json_encoder = json.JSONEncoder(True, True, True, True, False, 4)
                    json_data = json_encoder.encode(self.status)
                    fh = open(self.error_file, 'w+')
                    fh.write(json_data)
                    fh.close()
                except BaseException, ee:
                    self._output('Fatal Error | Could not log status to file {0} and {1}'.format(self.error_file, self.log_file), 0)
                    raise Exception(ee)

                # Output original error
                self._output('Fatal Error: ' + str(e), 0)
                self._output(tb, 1)
        else:
            # Set exit status variables
            self.status['time_end'] = str(datetime.now())
            self.status['exit'] = 'Success'
        finally:
            # Remove pseudo-PID file
            self._remove_pid_file()

            # Log truncated status dictionary to error log
            json_encoder = json.JSONEncoder(False, True, True, True, False, None)
            json_data = json_encoder.encode(self._trim_status())
            fh = open(self.log_file, 'a+')
            fh.write(json_data + '\n')
            fh.close()

            # Send correct unix status code
            if not success:
                sys.exit(1)

    return wrapper

def execute_safely(func):
    def wrapper(self, *args, **named_args):
        try:
            return func(self, *args, **named_args)
        except BaseException, e:
            # Catch all exceptions here so it can be logged in the
            # command history. Then raise the error again to be caught
            # by the catch-all, ensuring proper cleanup before exit.
            if type(args[0]) is list:
                command = ' '.join(str(x) for x in args[0])
            else:
                command = args[0]
            message = 'Command: {0} | {1}'.format(command, str(e))
            self._history('error', message)
            self._raise(e, message)
    return wrapper

def reload_environmental_info(func):
    def wrapper(self, *args, **named_args):
        try:
            return func(self, *args, **named_args)
        finally:
            self.load_info()
    return wrapper

# ==============================================================================
# Error Classes
# ==============================================================================
class ApplicationError(Exception):

    def __init__(self, value):
        self.value = value

    def __str__(self):
        return repr(self.value)

class ApplicationWarning(Exception):

    def __init__(self, value):
        self.value = value

    def __str__(self):
        return repr(self.value)

# ==============================================================================
# Main Application
# ==============================================================================
class Vmpy:

    # ==========================================================================
    # Setup aplication environment
    # ==========================================================================
    @sys_exit
    def __init__(self):
        '''
        A python interface wrapper for virtual-machine management on small scale
        cluster environments.

        This class automates virtual-machine backup, importing, and cloning both
        locally and remotely.

        It assumes:
        + KVM/QEMU/Libvirt virtual-machine management
        + Virsh management
        + Virtual-machine persistence using raw logical volumes
        + Virtual-machine networking with bridge/TAP interfaces

        In a large computing cluster, machine redundancy allows a setup where
        virtual-machine disk persistence exists on central file server(s). This
        script assumes virtual-machine disk images are stored locally on the
        Host OS.

        For command help, see -h. For complete documentation see the attached
        README.md file. If this file does not exist see the project website
        at http://github.com/chrislaskey/vmpy.
        '''

        # Begin outputting progress
        self._output('Bootstrapping application.', 2)

        # Set private variables.
        # Note: self.status is set in @sys_exit decorator
        self.data = {}
        self.data['vg_info'] = {}
        self.data['lv_info'] = {}
        self.data['vm_info'] = {}
        self.now = str(datetime.now().strftime('%Y%m%d-%H%M'))

        # Process variables.
        self.error_file = self.error_file.replace('<datetime>', self.now)

        # Parse command-line arguments.
        self._output('Parsing command-line arguments.', 2)
        self.args = self._load_arg_info()

        # Save arguments for detailed error logs.
        self.status['args'] = self.args.__dict__

        # Load environmental variables like defined vms, logical volumes, and
        # volume groups.
        self._output('Loading environment info', 2)
        self.load_info()

        # Now that basic setup is loaded, decide which action to take.
        # We'll wrap actions into try/except/else to guarantee logging of
        # both errors and successes.
        self.action()

    # --------------------------------------------------------------------------
    # Environment setup functions
    # --------------------------------------------------------------------------
    def _load_arg_info(self):
        '''
        Use the argparse module to parse command line arguments.
        Notice the use of subparsers, allowing different flags/options depending
        on the first argument word.
        '''

        # Create argparse instance
        preface = textwrap.dedent('''
            ABOUT

            vm.py is a python wrapper for the backup, adding, and cloning of
            virtual machines running on KVM/QEMU/Libvirt host machines.

            vm.py handles raw disk image backups (LVM logical volumes), and
            simplifies management with virsh.

            The three actions of vm.py are:

              ./vm.py backup
                  Backup a local VM to a disk image on the
                  host machine or remote machine via SSH.

              ./vm.py import
                  Import a local or remote VM backup to the host
                  machine. Import keeps essential values like UUID
                  and network MAC address the same. Other values like
                  the target logical volume are modifiable.
                  See import --help for a full list of options.

              ./vm.py clone
                  Create a new VM based on a local VM backup image,
                  remote VM backup image, or live VM. Cloning changes
                  unique identifiers like VM UUID and network MAC address.
                  Other VM values such as the VM name, networking
                  information, persistent disk location, etc, are
                  modifiable. See clone --help for full list of options.

            See `vm.py <action> --help` for specific information and commands for each action.

            COMMANDS

            ''')
        epilog = textwrap.dedent('''
            EPILOG

            See `vm.py <action> --help` for specific information and commands for
            each action.

            @author  Chris Laskey
            @contact chrislaskey.com
            @contact github.com/chrislaskey
            @updated 2012.07.18
            @version 1.8.9

            This script is licensed under a 4 clause MIT license.
            See LICENSE.txt for more information.

            For more technical documentation, see the README.md file or visit
            the project page on github: http://github.com/chrislaskey/vmpy.

            ''')
        parser = argparse.ArgumentParser(
            formatter_class=argparse.RawDescriptionHelpFormatter,
            description=preface,
            epilog=epilog
        )

        # Setup arguments
        config = parser.add_argument_group('Configuration options')
        config.add_argument('--configure', action="store_const", const=True, default=False, help='Run interactive configuration setup. Note: this is run automatically the first time.')
        config.add_argument('--list-config', action="store_const", const=True, default=False, help='List current configuration values.')
        config.add_argument('--block-size', action="store", default='512K', help='Set the blocksize for dd operations, i.e. `dd bs=<value> ...`')

        # Command arguments
        command = parser.add_argument_group('Misc command-line options')
        command.add_argument('--output-level', action="store", choices=['0','1','2','3','4'], default='1', help='Choose how verbose the output is (0=None, 1=Critical, 2=Important, 3=Verbose, 4=Debugging). Each level prints messages below it (e.g. 4 prints all.')
        command.add_argument('--headless', action="store_const", const=True, default=False, help='Run command from a headless source (e.g. not a human on a command line).')
        command.add_argument('--dev', action="store_const", const=True, default=False, help='Run in development mode (prints out trackback errors, etc).')

        # Create subparsers
        subparsers = parser.add_subparsers(dest='keyword', help='vm.py supports sub commands with their own options')

        # Backup subparser
        backup_subparser = subparsers.add_parser('backup', description='', help='vm.py backup')
        backup_required = backup_subparser.add_argument_group('Required arguments')
        backup_required.add_argument('name', help='Name of the VM to backup. Must be a name recognized by Virsh.')
        backup_required.add_argument('source', help='Target directory. Will attempt to create directory if it does not exist. A timestamp directory will be created inside the target directory and the backup files will be saved inside it.')

        backup_optional = backup_subparser.add_argument_group('Backup optional arguments')
        backup_optional.add_argument('--remote', action="store", metavar='<ssh-connection-information>', help='Backup file to a remote location over SSH.')

        backup_config = backup_subparser.add_argument_group('Backup configuration options')
        backup_config.add_argument('--compression', action="store", choices=['bzip2', 'gzip', 'none'], default='bzip2', help='Backup file to a remote location over SSH.')
        backup_config.add_argument('-I', '--identity-file', action="store", help='Identity file to use for remote ssh/scp connection.')

        # Import subparser
        import_subparser = subparsers.add_parser('import', description='', help='vm.py import')
        import_required = import_subparser.add_argument_group('Required arguments')
        import_required.add_argument('source', help='If importing up from local VM backup, source must be a directory. The directory should contain a <vm-name>.img, <vm-name>.xml and meta.txt file. If the --remote option is being used, this should be a remote directory.')
        import_required.add_argument('name', nargs='?', help='Name of the new virtual-machine. By default this will be the same name as the source VM.')

        import_optional = import_subparser.add_argument_group('Import optional arguments')
        import_optional.add_argument('--overwrite', action="store_const", const=True, default=False, help='Overwite any existing VM or VM raw storage logical volume. Default value is False, which raises an exception if either already exists.')
        import_optional.add_argument('--remote', action="store", metavar='<ssh-connection-information>', help='Import VM backup from a remote location over SSH.')
        import_optional.add_argument('-I', '--identity-file', action="store", help='Identity file to use for remote ssh/scp connection.')

        import_config = import_subparser.add_argument_group('Target VM configuration options')
        import_config.add_argument('--volume-group', action="store", help='Specify a target volume group. Without this the default is the source VMs value.')
        import_config.add_argument('--logical-volume', action="store", help='Specify a target logical volume. Without this the default is the source VMs value.')
        import_config.add_argument('--bridge', action="store", help='Specify a target networking bridge (e.g. br0). Without this the default is the source VMs value.')

        import_startup = import_subparser.add_argument_group('New VM startup options')
        import_startup.add_argument('--autostart', action="store_const", const=True, default=False, help='Autostart the new VM on boot. By default cloned VMs will not autostart on Host OS reboot.')
        import_startup.add_argument('--start', action="store_const", const=True, default=False, help='Boot the VM on clone completion. By default cloned VMs will not be booted.')

        # Clone subparser
        clone_subparser = subparsers.add_parser('clone', description='', help='vm.py clone')
        clone = clone_subparser.add_argument_group('Required arguments')
        clone.add_argument('source', help='If cloning from a VM backup, source must be a directory. The directory should contain a <vm-name>.img, <vm-name>.xml and meta.txt file. If the --live option is being used to clone a VM defined on the Host machine, source must be a <vm-name>')
        clone.add_argument('name', help='Name of the new virtual-machine.')

        clone_optional = clone_subparser.add_argument_group('Clone optional arguments')
        clone_optional.add_argument('--overwrite', action="store_const", const=True, default=False, help='Overwite any existing VM or VM raw storage logical volume. Default value is False, which raises an exception if either already exists.')
        clone_optional.add_argument('--live', action="store_const", const=True, default=False, help='Clone a running VM instead of cloning from a stored LVM image file and XML config.')
        clone_optional.add_argument('--remote', action="store", metavar='<ssh-connection-information>', help='Clone a VM backup from a remote location over SSH.')
        clone_optional.add_argument('-I', '--identity-file', action="store", help='Identity file to use for remote ssh/scp connection.')

        clone_config = clone_subparser.add_argument_group('Target VM configuration options')
        clone_config.add_argument('--volume-group', action="store", help='Specify a target volume group. Without this the default is the source VMs value.')
        clone_config.add_argument('--logical-volume', action="store", help='Specify a target logical volume. Without this the default is the source VMs value.')
        clone_config.add_argument('--logical-volume-size', action="store", help='Specify a target logical volume size. Should be specified in terms of gigabytes, ex: "25.00g". Without this the default is the source VMs value.')
        clone_config.add_argument('--bridge', action="store", help='Specify a target networking bridge (e.g. br0). Without this the default is the source VMs value.')
        clone_config.add_argument('--mac', action="store", help='Specify a target networking card MAC address. Default MAC range is 52:54:00:XX:XX:XX. Without this the default is the source VMs value.')

        clone_startup = clone_subparser.add_argument_group('Target VM startup options')
        clone_startup.add_argument('--autostart', action="store_const", const=True, default=False, help='Autostart the new VM on boot. By default cloned VMs will not autostart on Host OS reboot.')
        clone_startup.add_argument('--start', action="store_const", const=True, default=False, help='Boot the VM on clone completion. By default cloned VMs will not be booted.')

        # Parse args
        parsed = parser.parse_args()

        # Post process args

        # Set output level
        if parsed.headless:
            parsed.output_level = '0'

        # Add a trailing / to all source directories. clone --live is the
        # noteable exception, it expects a VM name.
        if not 'live' in parsed or not parsed.live:
            parsed.source = parsed.source.rstrip('/') + '/'

        # Verify identity file
        if hasattr(parsed, 'identity_file') and parsed.identity_file:
            if not os.path.isfile(parsed.identity_file):
                self._raise('Could not find identity file: "{0}"'.format(parsed.identity_file))

        return parsed

    # --------------------------------------------------------------------------
    # Environment setup utility functions
    # --------------------------------------------------------------------------
    def _set_pid_file(self):
        '''
        Create a pseudo unix PID file. It is locally stored, but keeps multiple
        versions of the application from executing at once and running the risk
        of `dd` commands going off the rails. If PID already exists, raise an
        error.
        '''
        if os.path.isfile(self.pid_file):
            self._raise('Warning: pid file "{0}" already exists. Either the script is being executed elsewhere or a previous call failed to cleanup the pid file. See the --remove-pid argument to force remove and continue."'.format(self.pid_file))

        timestamp = str(datetime.now())
        self._write_file(self.pid_file, timestamp)

    def _remove_pid_file(self, initial_check=False):
        '''
        Remove the PID file.
        '''
        if not os.path.isfile(self.pid_file):
            self._raise('Warning: pid file "{0}" could not be removed, as it does not exist. Likely removed while script is executing.'.format(self.pid_file))
        self._unlink_file(self.pid_file)

    def _trim_status(self):
        '''
        Return a smaller version of the status variable for the execution log.
        The verbose status variable is used in case of an error, but otherwise
        contains too much information to be logged for the general log.
        '''
        status = self.status
        if 'args' in status:
            del status['args']
        if 'command_history' in status:
            del status['command_history']
        if 'traceback' in status:
            del status['traceback']
        return status

    # --------------------------------------------------------------------------
    # Load data['*_info'] functions
    # --------------------------------------------------------------------------
    def load_info(self):
        '''
        Load (or reload) environmental information about VGs, LVs, and
        VMs.
        '''
        self._load_vg_info()
        self._load_lv_info()
        self._load_vm_info()

    def _load_vg_info(self):
        '''
        Parse Host OS volume groups
        '''
        self._output('Loading Host OS LVM Volume Group information.', 2)

        # Set base value
        self.data['vg_info'] = {}

        # Return list from `vgs` command
        separator = '::'
        command = ['vgs', '--separator={0}'.format(separator), '--units=g']
        self._output('Parsing volume group information: `{0}`'.format(' '.join(command)), 3)
        output = self._execute(command, output_level=3)

        # Extract volume group rows from output
        rows = output.split('\n')
        rows = filter(None, rows)
        headers = rows[0].split(separator)
        headers = [cleaned.strip() for cleaned in headers]
        vgs = rows[1:]
        if not vgs:
            self._output('No volume groups found: `{0}`'.format(' '.join(command)), 3)
            return False

        # Process each volume group
        for row in vgs:
            # Process volume group row and save them to a dictionary using the
            # header values as keys
            segments = row.split(separator)
            segments = [cleaned.strip() for cleaned in segments]
            values = dict(zip(headers, segments))
            volume_group = {segments[0]: values}

            # Save data
            self._output('  Volume group parsed: "{0}"'.format(segments[0]), 3)
            self._output('  Volume group values: {0}'.format(volume_group), 4)
            self.data['vg_info'].update(volume_group)

        return True

    def _load_lv_info(self):
        '''
        Parse Host OS logical volumes
        '''
        self._output('Loading Host OS LVM Logical Volume information.', 2)

        # Set base value
        self.data['lv_info'] = {}

        # Return list from `lvs` command
        separator = '::'
        command = ['lvs', '--separator={0}'.format(separator), '--units=g']
        self._output('Parsing logical volume information: `{0}`'.format(' '.join(command)), 3)
        output = self._execute(command, output_level=3)

        # Extract logical volume rows from output
        rows = output.split('\n')
        rows = filter(None, rows)
        headers = rows[0].split(separator)
        headers = [cleaned.strip() for cleaned in headers]
        lvs = rows[1:]
        if not lvs:
            self._output('No logical volumes found: `{0}`'.format(' '.join(command)), 3)
            return False

        # Process each volume group
        for row in lvs:
            # Process volume group row and save them to a dictionary using the
            # header values as keys
            segments = row.split(separator)
            segments = [cleaned.strip() for cleaned in segments]
            values = dict(zip(headers, segments))
            logical_volume = {(values['VG'], values['LV']): values}

            # Save data
            self._output('  Logical volume parsed: "{0}"'.format(segments[0]), 3)
            self._output('  Logical volume values: {0}'.format(logical_volume), 4)
            self.data['lv_info'].update(logical_volume)

        return True

    def _load_vm_info(self, name=None, file=None, raw=None):
        '''
        Parse and load info for all virtual-machines defined in `virsh`
        '''
        self._output('Loading Host OS Virtual Machine information.', 2)

        # Set base value
        self.data['vm_info'] = {}

        # Get virsh list and parse results
        command = ['virsh', 'list', '--all']
        self._output('Parsing defined virtual-machine information: `{0}`'.format(' '.join(command)), 3)
        output = self._execute(command, output_level=3)

        # Extract virtual machine rows from output
        rows = output.split('\n')
        headers = rows[0:2]
        headers = [cleaned.strip() for cleaned in headers]
        vms = rows[2:]
        vms = filter(None, vms)
        if not vms:
            self._output('No defined virtual-machines found: `{0}`'.format(' '.join(command)), 3)
            return False

        # Process virtual machine
        for row in vms:
            # Parse row data into columns and start vm data dictionary
            columns = row.split()
            columns = [cleaned.strip() for cleaned in columns]
            values = {}
            values['name'] = columns[1]
            values['status'] = ' '.join(columns[2:])

            # Load VM XML
            command = ['virsh', 'dumpxml', '{0}'.format(values['name'])]
            self._output('Retrieving XML for virtual machine: `{0}`'.format(' '.join(command)), 4)
            xml = self._execute(command, output_level=3)

            # Send XML to be parsed for additional vm information
            xml_info = self._parse_vm_xml(xml)
            values.update(xml_info)

            # Add in LV size information
            lv_info = self._return_lvm_info_by_path(values['disk'])
            values.update(lv_info)

            # Add vm name as dictionary key
            virtual_machine = {values['name']: values}

            # # Save data
            debug_output = values.copy()
            if 'xml' in debug_output:
                del debug_output['xml']
            self._output('  Virtual machine parsed "{0}"'.format(values['name']), 3)
            self._output('  Virtual machine values: {0}'.format(debug_output), 4)
            self.data['vm_info'].update(virtual_machine)

        return True

    # --------------------------------------------------------------------------
    # Load data['*_info'] utility functions
    # --------------------------------------------------------------------------
    def _parse_vm_xml(self, raw):
        '''
        A helper function for _load_vm_info that parses VM XML and
        returns a dictionary of info values
        '''

        # Set keys and create default parsed dictionary
        keys = ('name', 'uuid', 'disk', 'disk_file', 'mac', 'bridge', 'xml')
        parsed = dict([(key, None) for key in keys])

        # Get XML
        if not raw:
            return {}

        # Parse XML
        parsed['xml'] = raw
        xml = ElementTree.fromstring(raw)

        # Get name and uuid
        try:
            if xml.find('name') is not None:
                parsed['name'] = xml.findtext('name')
            if xml.find('uuid') is not None:
                parsed['uuid'] = xml.findtext('uuid')
        except AttributeError:
            return parsed

        # Parse devices tree
        try:
            devices = xml.find('devices')
        except AttributeError:
            return parsed

        # Disk
        try:
            for disk in devices.findall('disk'):
                if disk.get('device') == 'disk':
                    source = disk.find('source')
                    parsed['disk'] = source.get('dev')
        except AttributeError:
            return parsed

        # File disk
        if not parsed['disk']:
            try:
                for disk in devices.findall('disk'):
                    if disk.get('device') == 'disk':
                        source = disk.find('source')
                        parsed['disk_file'] = source.get('file')
            except AttributeError:
                pass

        # MAC address and Bridge device
        try:
            for interface in devices.findall('interface'):
                if interface.find('mac') is not None:
                    parsed['mac'] = interface.find('mac').get('address')
                if interface.find('source') is not None:
                    parsed['bridge'] = interface.find('source').get('bridge')
        except AttributeError:
            return parsed

        return parsed

    def _return_lvm_info_by_path(self, path):
        '''
        Helper function to parse `lvs` information by path.
        Reliable way to get logical volume and volume group information
        by disk path. Better than parsing disk path and assuming it follows
        the /dev/volume_group/logical_volume standard path.
        '''

        # Set default dictionary
        keys = ('disk_size', 'logical_volume', 'volume_group')
        values = dict([(key, None) for key in keys])

        # Return if path is null
        if not path:
            return values

        # Get `lvs` output
        separator = '::'
        command = ['lvs','--separator={0}'.format(separator), '--units=g', '{0}'.format(path)]
        self._output('Retrieving LVM information for disk path: `{0}`'.format(' '.join(command)), 3)
        output = self._execute(command, output_level=3)

        # Parse information
        row = output.split('\n')[1:2]
        row = str(row[0])
        columns = row.split(separator)
        columns = [cleaned.strip() for cleaned in columns]

        # Assign and return dictionary values
        values = {}
        values['logical_volume'] = columns[0]
        values['volume_group'] = columns[1]
        values['disk_size'] = self.lv_info((values['volume_group'], values['logical_volume']), 'LSize', False)
        return values

    # --------------------------------------------------------------------------
    # Load data['*_info'] interface methods
    # --------------------------------------------------------------------------
    def vg_info(self, vg, attribute=None, raise_exception=True):
        '''
        Return vg information. Requires a vg name. If attribute is given, will
        return the attribute value. If attribute is not given, will return the
        complete info dictionary. By default an exception will be raised if
        either the vg or attribute does not exist. This ensures there is no
        confusion between False-y attribute values and non-existent ones.
        '''
        try:
            if not attribute:
                return self.data['vg_info'][vg]
            else:
                return self.data['vg_info'][vg][attribute]
        except KeyError:
            if raise_exception:
                self._raise('The requested (vg, attribute) pair does not exist: "self.vg_info({0}, {1})".'.format(vg, attribute))

    def lv_info(self, lv_tuple, attribute=None, raise_exception=True):
        '''
        Return lv information. Requires a lv name. If attribute is given, will
        return the attribute value. If attribute is not given, will return the
        complete info dictionary. By default an exception will be raised if
        either the lv or attribute does not exist. This ensures there is no
        confusion between False-y attribute values and non-existent ones.
        '''
        try:
            if not attribute:
                return self.data['lv_info'][lv_tuple]
            else:
                return self.data['lv_info'][lv_tuple][attribute]
        except KeyError:
            if raise_exception:
                self._raise('The requested (lv_tuple, attribute) pair does not exist: "self.lv_info({0}, {1})".'.format(lv_tuple, attribute))

    def vm_info(self, vm, attribute=None, raise_exception=True):
        '''
        Return vm information. Requires a vm name. If attribute is given, will
        return the attribute value. If attribute is not given, will return the
        complete info dictionary. By default an exception will be raised if
        either the vm or attribute does not exist. This ensures there is no
        confusion between False-y attribute values and non-existent ones.
        '''
        try:
            if not attribute:
                return self.data['vm_info'][vm]
            else:
                return self.data['vm_info'][vm][attribute]
        except KeyError:
            if raise_exception:
                self._raise('The requested (vm, attribute) pair does not exist: "self.vm_info({0}, {1})".'.format(vm, attribute))

    def vm_info_search(self, attribute, value, raise_exception=True):
        '''
        Search host machine VMs for a particular attribute value. If there is
        a match, return a list of matching VM names. If attribute does not
        exist, raise an exception.
        '''
        try:
            matches = []
            for vm in self.data['vm_info'].itervalues():
                if vm[attribute] == value:
                    matches.append(vm['name'])
        except KeyError:
            if raise_exception:
                self._raise('The attribute "{0}" does not exist.'.format(attribute))
        finally:
            return list(set(matches))

    def vm_info_is_unique(self, attribute, value, raise_exception=True):
        '''
        Verify given attribute:value pair does not exist in any of the VMs
        defined on the system. Both attribute and value is required. By
        default an exception will be raised if a vm does not have the
        attribute. Otherwise a boolean will be returned.
        '''
        for vm in self.data['vm_info'].itervalues():
            try:
                vm[attribute]
            except KeyError:
                if raise_exception:
                    self._raise('The requested attribute "{0}" does not exit in vm info.'.format(attribute))
                continue

            if vm[attribute] == value:
                return False

        return True

    def vm_count(self):
        '''
        Return the number of VMs defined on the host machine.
        '''
        return len(self.data['vm_info'])

    # ==========================================================================
    # Action functions
    # ==========================================================================
    def action(self):
        '''
        Determine main action, backup, import or clone VMs.
        '''
        self._output('Determining action.', 2)

        if not self.args.keyword:
            custom_message = 'No action command received. See -h for more information.'
            self._raise(custom_message)

        if self.args.keyword == 'backup':
            return self.backup()

        if self.args.keyword == 'import':
            return self.import_vm()

        if self.args.keyword == 'clone':
            return self.clone()

    # --------------------------------------------------------------------------
    # Action common functions - general functions
    # --------------------------------------------------------------------------
    def _create_vm_meta(self, vm):
        '''
        Create a dictionary of helpful meta-data about the VM from host machine
        environment.
        '''
        # Set variables
        if 'compression' in self.args:
            compression = self.args.compression
        else:
            compression = 'none'

        if compression != 'none':
            compression_extension = '.' + compression
        else:
            compression_extension = ''

        # Save simple values
        #
        # If bzip2 compression is used there is no reliable way to
        # determine disk size ahead of time. Knowing, and later storing, the
        # image_size value is helpful when creating a new LV for the disk image.
        meta = {}
        meta['date'] = self.now
        meta['command'] = self.status['command']
        meta['name'] = self.vm_info(vm, 'name')
        meta['xml'] = './{0}.xml'.format(vm)
        meta['image'] = './{0}.img{1}'.format(vm, compression_extension)
        meta['image_size'] = self.vm_info(vm, 'disk_size')
        meta['compression'] = compression
        meta['logical_volume'] = self.vm_info(vm, 'logical_volume')
        meta['volume_group'] = self.vm_info(vm, 'volume_group')
        meta['bridge'] = self.vm_info(vm, 'bridge')
        meta['mac'] = self.vm_info(vm, 'mac')
        meta['uuid'] = self.vm_info(vm, 'uuid')
        meta['disk'] = self.vm_info(vm, 'disk')
        meta['disk_file'] = self.vm_info(vm, 'disk_file')
        return meta

    def _load_vm_meta(self, raw_data):
        '''
        Load meta values from unparsed JSON.
        '''
        try:
            return json.loads(raw_data)
        except ValueError, e:
            self._raise(e, 'Could not parse JSON meta data, JSON appears to be malformed.')

    def _load_vm_meta_from_file(self, path):
        '''
        Load meta values from backup meta.txt file.
        '''
        raw_data = self._read_file(path)
        return self._load_vm_meta(raw_data)

    # --------------------------------------------------------------------------
    # Action common functions - virsh commands
    # --------------------------------------------------------------------------
    # Note: Virsh VM commands are indempotent. For example, a call to resume an
    # already running VM does not throw an error.
    def _vm_autostart(self, vm):
        command = ['virsh', 'autostart', vm]
        self._output('Setting VM to autostart when Host OS reboots: `{0}`.'.format(' '.join(command)), 2)
        return self._execute(command, boolean=True)

    def _vm_start(self, vm):
        command = ['virsh', 'start', vm]
        self._output('Starting the currently shut off VM "{0}": `{1}`.'.format(vm, ' '.join(command)), 2)
        return self._execute(command, boolean=True)

    def _vm_suspend(self, vm):
        command = ['virsh', 'suspend', vm]
        self._output('Suspending the currently running VM "{0}": `{1}`.'.format(vm, ' '.join(command)), 2)
        return self._execute(command, boolean=True)

    def _vm_resume(self, vm):
        command = ['virsh', 'resume', vm]
        self._output('Resuming the currently suspended VM "{0}": `{1}`.'.format(vm, ' '.join(command)), 2)
        return self._execute(command, boolean=True)

    def _vm_shutdown(self, vm):
        command = ['virsh', 'shutdown', vm]
        self._output('Shutting down the currently running VM "{0}": `{1}`.'.format(vm, ' '.join(command)), 2)
        return self._execute(command, boolean=True)

    def _vm_destroy(self, vm):
        command = ['virsh', 'destroy', vm]
        self._output('Destroying the currently running VM "{0}": `{1}`.'.format(vm, ' '.join(command)), 2)
        return self._execute(command, boolean=True)

    @reload_environmental_info
    def _vm_define(self, xml_file_path):
        command = ['virsh', 'define', xml_file_path]
        self._output('Defining VM "{0}": `{1}`.'.format(xml_file_path, ' '.join(command)), 2)
        return self._execute(command, boolean=True)

    @reload_environmental_info
    def _vm_undefine(self, vm):
        self._vm_destroy(vm)
        command = ['virsh', 'undefine', vm]
        self._output('Destroyed any VM instance and undefined VM "{0}": `{1}`.'.format(vm, ' '.join(command)), 2)
        return self._execute(command, boolean=True)

    # --------------------------------------------------------------------------
    # Action common functions - LVM commands
    # --------------------------------------------------------------------------
    def _vg_has_space(self, vg, request_size_in_g):
        '''
        Compare specified volume group's remaining space with a requested size
        and return a Boolean.
        '''
        # Extract float values from size strings
        if request_size_in_g[-1].lower() == 'g':
            size_in_g = request_size_in_g[:-1]
        request = float(size_in_g)
        vg_free_string = self.vg_info(vg, 'VFree')
        vg_free = vg_free_string[:-1]
        vg_free = float(vg_free)

        # Return boolean value
        return vg_free > request

    @reload_environmental_info
    def _lv_create(self, lv_size, lv_name, vg_name):
        '''
        Create a new logical volume. Will raise an error if logical volume
        already exists.
        '''
        # Set variables
        vg_path = '/dev/{0}'.format(vg_name)
        lv_path = '{0}/{1}'.format(vg_path, lv_name)
        lv_exists = bool(self.lv_info((vg_name, lv_name), None, False))

        # Check if logical volume already exists
        if lv_exists:
            self._raise('Could not create logical volume. The logical volume already exists on the host machine: "{0}"'.format(lv_path))

        # Verify enough space exists in volume group
        if not self._vg_has_space(vg_name, lv_size):
            message = 'Could not create LV sized "{0}" in VG "{1}", not enough space.'.format(lv_name, vg_path)
            self._raise(message)

        # Create logical volume
        command = ['lvcreate', '-L', '{0}'.format(lv_size), '-n', '{0}'.format(lv_name), vg_path]
        self._output('Creating LV: `{0}`'.format(' '.join(command)), 2)
        return self._execute(command)

    @reload_environmental_info
    def _lv_create_snapshot(self, vm, snapshot_name, snapshot_size='2.00g'):
        '''
        Create a new logical volume snapshot. Will raise an error if logical
        volume already exists.
        '''
        # Set variables
        vm_vg = self.vm_info(vm, 'volume_group')
        vm_path = self.vm_info(vm, 'disk')

        # Verify enough space exists in volume group
        if not self._vg_has_space(vm_vg, snapshot_size):
            message = 'Could not create LV snapshot sized "{0}" in VG "{1}", not enough space.'.format(snapshot_size, vm_vg)
            self._raise(message)

        # Verify vm_path exists on local machine
        if not os.path.exists(vm_path):
            message = 'Could not create LV snapshot in "{0}", path does not exist.'.format(vm_path)
            self._raise(message)

        # Create snapshot
        command = ['lvcreate', '--snapshot', '-L', '{0}'.format(snapshot_size), '-n', '{0}'.format(snapshot_name), vm_path]
        self._output('Creating LV snapshot: `{0}`'.format(' '.join(command)), 2)
        return self._execute(command)

    @reload_environmental_info
    def _lv_import(self, source_path, target_path, compression='none'):
        '''
        Copy the contents of the source path to the target LV using DD. Source
        may be a backup image of a LV or live snapshot.
        '''
        # Verify source_path exists on local machine
        if not os.path.exists(source_path):
            message = 'Could not import LV, source path does not exist: "{0}".'.format(source_path)
            self._raise(message)

        # Verify target_path exists on local machine
        if not os.path.exists(target_path):
            message = 'Could not import LV, target path does not exist: "{0}".'.format(target_path)
            self._raise(message)

        # Create commands
        command_queue = []
        command_queue.append(['dd', 'bs={0}'.format(self.args.block_size), 'if={0}'.format(source_path)])
        if compression != 'none':
            command_queue.append(['{0}'.format(compression), '-d'])
        command_queue.append(['dd', 'bs={0}'.format(self.args.block_size), 'of={0}'.format(target_path)])

        # Execute commands
        self._output('Importing LV', 2)
        self._execute_queue(command_queue)
        self._output('Successful LV import', 2)

    @reload_environmental_info
    def _lv_remove(self, lv_path):
        '''
        Remove a LV on the host machine.
        '''
        # Verify logical volume exists
        if not os.path.exists(lv_path):
            message = 'Could not remove LV "{0}", logical volume does not exist.'.format(lv_path)
            self._raise(message)

        # Remove logical volume
        command = ['lvremove', '-f', '{0}'.format(lv_path)]
        self._output('Removing logical volume: `{0}`.'.format(' '.join(command)), 2)
        return self._execute(command)

    # --------------------------------------------------------------------------
    # Action common functions - VM functions
    # --------------------------------------------------------------------------
    def _vm_remove(self, name):
        '''
        Compound function to completely remove a VM from disk
        '''
        path = self.vm_info(name, 'disk')
        self._output('Removing VM "{0}" and VM disk "{1}"'.format(name, path))
        return self._vm_undefine(name) and self._lv_remove(path)

    def _vm_resolve_conflicts(self, potential_conflicts):
        '''
        Identify conflicts between the import/clone target and currently
        defined VMs on the host machine. If there are conflicts, attempt to
        remove VM and VM disk. If --overwrite is set try to remove. If running
        headless and --overwrite is not set, raise an error message. Otherwise
        prompt the user for action.
        '''
        prompt = (self.args.output_level > 0)

        # Search list for potential conflicts with VMs defined on the host.
        for i in range(len(potential_conflicts)):
            (attribute, value) = potential_conflicts[i]
            conflicts = self.vm_info_search(attribute, value)

            if conflicts:
                for vm_name in conflicts:
                    if self.args.overwrite:
                        self._vm_remove(vm_name)
                        continue

                    error = 'A VM defined on the host machine "{0}" shares a conflicting attribute: value, "{1}: {2}".'.format(vm_name, attribute, value)
                    if not prompt:
                        self._raise(error)

                    message = '{0} Remove active VM "{1}"? [y/cancel]:'.format(error, vm_name)
                    input = raw_input(message)

                    if input.lower() in ['y', 'yes']:
                        self._vm_remove(vm_name)
                    if input.lower() in ['quit', 'cancel']:
                        self._output('Exiting with conflicts. Resolve conflicts in order to complete action.')
                        sys.exit(0)
                    else:
                        self._vm_resolve_conflicts(potential_conflicts[i:])

    # --------------------------------------------------------------------------
    # Action common functions - Meta and XML functions
    # --------------------------------------------------------------------------
    def _verify_target_meta(self, meta):
        '''
        Verify target meta data.
        '''
        # Verify volume group exists and has space for logical volume
        if not self.vg_info(meta['volume_group'], None, False):
            self._raise('The target volume group does not exist on the local machine: "{0}"'.format(meta['volume_group']))
        if not self._vg_has_space(meta['volume_group'], meta['image_size']):
            self._raise('The target volume group does not have enough space for new logical volume: "{0}"'.format(meta['volume_group']))

        # Verify bridge exists
        bridge_command = ['ifconfig', meta['bridge']]
        if not self._execute(bridge_command, boolean=True):
            self._raise('The target bridge does not exist: `{0}` returned non-zero.'.format(' '.join(bridge_command)))

        # Verify MAC is not empty
        if not meta['mac']:
            self._raise('The target mac address can not be empty: "{0}"'.format(meta['mac']))

    def _load_target_meta(self, meta, action='clone'):
        '''
        Override source meta values with any passed command line arguments and
        return target meta.
        '''
        self._output('Loading target meta: "{0}"'.format(meta), 3)

        if hasattr(self.args, 'name') and self.args.name:
            meta['name'] = self.args.name

        if action == 'clone':
            meta['uuid'] = None

        if hasattr(self.args, 'volume_group') and self.args.volume_group:
            meta['volume_group'] = self.args.volume_group

        if hasattr(self.args, 'logical_volume') and self.args.logical_volume:
            meta['logical_volume'] = self.args.logical_volume
        elif self.args.name:
            meta['logical_volume'] = self.args.name

        if hasattr(self.args, 'logical_volume_size') and self.args.logical_volume_size:
            meta['logical_volume_size'] = self.args.logical_volume_size
        else:
            meta['logical_volume_size'] = meta['image_size']

        if hasattr(self.args, 'bridge') and self.args.bridge:
            meta['bridge'] = self.args.bridge

        if hasattr(self.args, 'mac') and self.args.mac:
            meta['mac'] = self.args.mac
        elif action == 'clone':
            meta['mac'] = self._create_mac_address()

        meta['disk'] = '/dev/' + meta['volume_group'] + '/' + meta['logical_volume']

        return meta

    def _pprint_meta(self, source_meta, target_meta=None):
        '''
        Pretty print the source_meta and target_meta value.
        '''
        order = [
            ('name', 'VM Name'),
            ('disk_file', 'Disk File'),
            ('disk', 'Disk LVM'),
            ('logical_volume', 'Logical Volume'),
            ('volume_group', 'Volume Group'),
            ('xml', 'XML File'),
            ('image', 'Disk Image File'),
            ('image_size', 'Disk Image File Size'),
            ('compression', 'Disk Image File Compression'),
            ('uuid', 'VM UUID'),
            ('mac', 'VM Networking MAC Address'),
            ('bridge', 'VM Networking Bridge')
        ]
        spacer = '    '

        if source_meta:
            source = '\nSource VM Information:\n'
            for key, title in order:
                if key in source_meta:
                    source = source + spacer + '{0}: {1}\n'.format(title, source_meta.get(key))
            self._output(source)

        if target_meta:
            target = '\nTarget VM Information:\n'
            for key, title in order:
                if key in target_meta:
                    target = target + spacer + '{0}: {1}\n'.format(title, target_meta.get(key))
            self._output(target)

    def _load_target_xml(self, source_xml, source_meta, target_meta, action='clone'):
        '''
        Create target XML by overwriting values from the source XML and
        returning the modified data.
        '''
        # Future: Current implementation is brittle. Regex and XML parsing
        # have their own problems, but they're worth a second look.
        if not source_xml:
            self._raise('Could not create target XML, source XML is empty.')
        else:
            target_xml = source_xml

        # Replace name
        source = '<name>' + source_meta['name'] + '</name>'
        target = '<name>' + target_meta['name'] + '</name>'
        if target_xml.find(source) == -1:
            self._raise('Could not create target XML, value "{0}" not found in source XML.'.format(source))
        target_xml = target_xml.replace(source, target)

        # Replace disk
        source = "<source dev='" + source_meta['disk'] + "'/>"
        target = "<source dev='" + target_meta['disk'] + "'/>"
        if target_xml.find(source) == -1:
            self._raise('Could not create target XML, value "{0}" not found in source XML.'.format(source))
        target_xml = target_xml.replace(source, target)

        # Replace MAC
        source = "<mac address='" + source_meta['mac'] + "'/>"
        target = "<mac address='" + target_meta['mac'] + "'/>"
        if target_xml.find(source) == -1:
            self._raise('Could not create target XML, value "{0}" not found in source XML.'.format(source))
        target_xml = target_xml.replace(source, target)

        # Replace Bridge
        source = "<source bridge='" + source_meta['bridge'] + "'/>"
        target = "<source bridge='" + target_meta['bridge'] + "'/>"
        if target_xml.find(source) == -1:
            self._raise('Could not create target XML, value "{0}" not found in source XML.'.format(source))
        target_xml = target_xml.replace(source, target)

        # Remove UUID line
        if action == 'clone':
            source = "<uuid>" + source_meta['uuid'] + "</uuid>"
            target = ""
            if target_xml.find(source) == -1:
                self._raise('Could not create target XML, could not remove UUID line. Value "{0}" not found in source XML.'.format(source))
            target_xml = target_xml.replace(source, target)

        # Return target XML
        return target_xml

    # --------------------------------------------------------------------------
    # Action function - Backup
    # --------------------------------------------------------------------------
    def backup(self):
        '''
        Take a VM and create a backup of its configuration (XML), raw
        disk-image (LVM logical volume), and some meta-data about the
        VM (meta). Save these files either locally or remotely.
        '''
        self._output('Starting Backup action.', 2)

        # Verify VM exists
        if not self.vm_info(self.args.name, None, False):
            self._raise('Could not find VM named: "{0}"'.format(self.args.name))

        # Set variables
        vm = self.args.name
        initial_vm_status = self.vm_info(vm, 'status')
        snapshot_name = '{0}.snapshot'.format(vm)
        vm_path = self.vm_info(vm, 'disk')
        snapshot_path = '{0}.snapshot'.format(vm_path)

        # If VM is running suspend it. Cache status for later.
        if initial_vm_status == 'running':
            self._vm_suspend(vm)

        # Create a LV snapshot
        self._lv_create_snapshot(vm, snapshot_name)

        # If VM was running (refer to cached variable), restart it.
        if initial_vm_status == 'running':
            self._vm_resume(vm)

        # Branch to either local or remote backup to save image
        try:
            if self.args.remote:
                self._backup_remote()
                success_message = 'Success: completed remote backup of VM "{0}" to "{1}".'.format(vm, '{0}:{1}'.format(self.args.remote, self.args.name))
            else:
                self._backup_local()
                success_message = 'Success: completed backup of VM "{0}" to "{1}".'.format(vm, '{0}{1}'.format(self.args.source, vm))
        except BaseException, e:
            self._raise(e)
        finally:
            # If copying snapshot fails we ensure the LV snapshot is removed,
            # preventing an unstable scenario when running from an unmonitored
            # terminal (such as a backup script on a cron job).
            self._lv_remove(snapshot_path)

        # Success message
        self._output(success_message)

    # --------------------------------------------------------------------------
    # Action function - Backup Remote
    # --------------------------------------------------------------------------
    def _backup_remote(self):
        '''
        Backup VM meta info, XML and LV snapshot to a remote location via `ssh`
        '''
        self._output('Executing remote backup action', 2)

        # Verify remote directory
        self._backup_remote_directory()

        # Backup our internal meta data
        self._backup_remote_meta_info()

        # Backup `virsh dumpxml` output
        self._backup_remote_xml()

        # Backup logical volume snapshot to disk image file using `dd`
        self._backup_remote_lv()

    def _backup_remote_directory(self):
        '''
        Verify the remote directory exists. If not, attempt to create it.
        '''
        command = self._remote_ssh_command(['mkdir', '-p', '{0}'.format(self.args.source)])
        self._output('Verifying the remote directory over ssh, creating it if needed: {0}'.format(' '.join(command)), 2)
        self._execute(command)

    def _backup_remote_meta_info(self):
        '''
        Send the VM meta file over `scp`
        '''
        # Save locally then transfer via SCP. Not ideal but popen() has trouble
        # with directional pipes without resorting to shell=True. Since we have
        # user input we don't want to use shell=True.
        local_meta_file = '{0}-{1}.temp.meta.txt'.format(self.args.name, self.now)
        self._output('Writing temporary meta info file locally at "{0}" before transfering via SCP remotely.'.format(local_meta_file), 2)
        meta_dict = self._create_vm_meta(self.args.name)
        meta_json = self._return_json(meta_dict)
        self._write_file(local_meta_file, meta_json)

        # Display action/meta information
        self._output('Backup VM "{0}" to "{1}"'.format(self.args.name, self.args.source))
        self._pprint_meta(meta_dict)

        self._output('Now executing SCP file transfer of local meta info file.', 2)
        target = '{0}meta.txt'.format(self.args.source)
        command = self._remote_target_scp_command(local_meta_file, target)
        self._execute(command)

        self._output('Unlinking the local temporary meta info file at "{0}".'.format(local_meta_file), 2)
        self._unlink_file(local_meta_file)

    def _backup_remote_xml(self):
        '''
        Send the VM XML file over `scp`
        '''
        # Save locally then transfer via SCP. Not ideal but popen() has trouble
        # with directional pipes without resorting to shell=True. Since we have
        # user input we don't want to use shell=True.
        target_xml_file = os.path.realpath('{0}-{1}.temp.xml'.format(self.args.name, self.now))
        self._output('Writing temporary VM XML file locally at "{0}" before transfering via SCP remotely.'.format(target_xml_file), 2)
        self._write_file(target_xml_file, self.vm_info(self.args.name, 'xml'))

        self._output('Now executing SCP file transfer of local VM XML file', 2)
        target = '{0}{1}.xml'.format(self.args.source, self.args.name)
        command = self._remote_target_scp_command(target_xml_file, target)
        self._execute(command)

        self._output('Unlinking the local temporary VM XML file at "{0}".'.format(target_xml_file), 2)
        self._unlink_file(target_xml_file)

    @execute_safely
    def _backup_remote_lv(self):
        '''
        Convert the LV snapshot to a disk image in a remote location using `ssh`.
        If specified, use compression on local side first.
        '''
        # Set variables
        vm = self.args.name
        vm_path = self.vm_info(vm, 'disk')
        if self.args.compression != 'none':
            zip_extension = '.' + self.args.compression
            zip_command = [str(self.args.compression), '-c']
        else:
            zip_extension = ''
            zip_command = None
        of = '{0}{1}.img{2}'.format(self.args.source, vm, zip_extension)

        # Create commands
        command_queue = []

        # Add dd command
        command_queue.append(['dd', 'bs={0}'.format(self.args.block_size), 'if={0}.snapshot'.format(vm_path)])

        # Add zip command
        if zip_command:
            command_queue.append(zip_command)

        # Add remote ssh command
        ssh_command = self._remote_ssh_command(['dd', 'bs={0}'.format(self.args.block_size), 'of={0}'.format(of)])
        command_queue.append(ssh_command)

        # Execute commands
        self._output('Backing Up VM disk image. This will take time.', show_timestamp=True)
        self._output('Starting dd remote backup', 2)
        self._execute_queue(command_queue)
        self._output('Successfully completed dd remote backup', 2)

    # --------------------------------------------------------------------------
    # Action function - Backup Local
    # --------------------------------------------------------------------------
    def _backup_local(self):
        '''
        Backup VM meta info, XML and LV snapshot to local directory
        '''
        self._output('Executing local backup action', 2)

        # Setup local vm storage directory
        self._verify_local_vm_storage()

        # Backup our internal meta data
        self._backup_local_meta_info()

        # Backup `virsh dumpxml` output
        self._backup_local_xml()

        # Backup logical volume snapshot to disk image file using `dd`
        self._backup_local_lv()

    def _verify_local_vm_storage(self):
        '''
        Verify the path exists. If it does not, stepwise check each directory
        and attempt to create the full path. Save the parsed path in the arg
        array.
        '''
        # Set variables
        path = self.args.source

        # Create directory step-wise if does not already exist
        if not os.path.isdir(path):
            try:
                os.makedirs(path)
            except IOError, e:
                self._raise(e, 'Could not create storage directory in "{0}"'.format(path))
            except OSError:
                pass

        self._output('Verified storage directory in "{0}"'.format(path), 2)

    def _backup_local_meta_info(self):
        '''
        Backup VM metadata info file
        '''
        # Backup meta to file
        meta_file = '{0}/meta.txt'.format(self.args.source)
        meta_dict = self._create_vm_meta(self.args.name)
        meta_json = self._return_json(meta_dict)
        self._write_file(meta_file, meta_json)

        # Display action/meta information
        self._output('Backup VM "{0}" to "{1}"'.format(self.args.name, self.args.source))
        self._pprint_meta(meta_dict)

    def _backup_local_xml(self):
        '''
        Backup VM XML to file
        '''
        xml_file = '{0}/{1}.xml'.format(self.args.source, self.args.name)
        self._write_file(xml_file, self.vm_info(self.args.name, 'xml'))

    @execute_safely
    def _backup_local_lv(self):
        '''
        Backup VM logical volume snapshot to a disk image, using compression
        if specified.
        '''
        # Set variables
        vm = self.args.name
        vm_path = self.vm_info(vm, 'disk')
        if self.args.compression != 'none':
            zip_extension = '.' + self.args.compression
            zip_command = [str(self.args.compression), '-c']
        else:
            zip_extension = ''
            zip_command = None
        of = '{0}{1}.img{2}'.format(self.args.source, vm, zip_extension)

        # Create commands
        command_queue = []
        command_queue.append(['dd', 'bs={0}'.format(self.args.block_size), 'if={0}.snapshot'.format(vm_path)])
        if zip_command:
            command_queue.append(zip_command)
        command_queue.append(['dd', 'bs={0}'.format(self.args.block_size), 'of={0}'.format(of)])

        # Execute commands
        self._output('Backing Up VM disk image. This will take time.', show_timestamp=True)
        self._output('Starting dd local backup', 2)
        self._execute_queue(command_queue)
        self._output('Successfully completed dd local backup', 2)

    # --------------------------------------------------------------------------
    # Action function - Import
    # --------------------------------------------------------------------------
    def import_vm(self):
        '''
        Import a new VM from a VM backup image. Default action is to load from a
        backup directory containing a meta file, XML file and VM disk image. If
        the remote argument is set, will pipe the meta file, XML file and VM disk
        image from a remote location using SSH.
        '''
        self._output('Starting Import action.', 2)

        # Determine whether this is a live backup or backup from storage.
        if self.args.remote:
            data = self._import_remote()
            success_message = 'Success: imported VM from a remote VM backup directory "{0}".'.format('{0}:{1}'.format(self.args.remote, self.args.source))
        else:
            data = self._import_local()
            success_message = 'Success: imported VM from a local VM backup directory "{0}".'.format(self.args.source)

        # virsh define target_xml file
        self._vm_define(data['target_xml_file'])

        # Boot VM if argument has been passed
        if self.args.start:
            self._vm_start(data['target_name'])

        # Add new VM to autostart list if the autostart argument has been passed
        if self.args.autostart:
            self._vm_autostart(data['target_name'])

        # Remove temporary target_xml_file
        self._unlink_file(data['target_xml_file'])

        # Print success message and warning to change hostname
        self._output(success_message)
        self._output('\n**Note: Guest OS may need additional configuration.')
        self._output('Changing hostname can be done by by updating values ' + \
                     '/etc/hostname and /etc/hosts and using `hostname` ' + \
                     'command.')

    # --------------------------------------------------------------------------
    # Action function - Import Remote
    # --------------------------------------------------------------------------
    def _import_remote(self):
        '''
        Import a VM from a remote backup image over ssh.
        '''
        self._output('Executing remote import action', 2)

        # Set variables
        return_data = {}
        remote_address = self.args.remote
        remote_dir = self.args.source
        remote_path = '{0}:{1}'.format(remote_address, remote_dir)

        # Confirm meta.txt file exists
        self._output('Confirming meta.txt file exists in remote directory: "{0}"'.format(remote_path), 2)
        command = self._remote_ssh_command(['test', '-f', '{0}/meta.txt'.format(remote_dir)])
        if not self._execute(command, boolean=True):
            self._raise('The required meta.txt file does not exist in remote directory: "{0}"'.format(remote_path))

        # Return and parse remote meta.txt
        self._output('Retrieving meta.txt file data from remote directory: "{0}"'.format(remote_path), 2)
        command = self._remote_ssh_command(['cat', '{0}/meta.txt'.format(remote_dir)])
        source_meta_data = self._execute(command)
        source_meta = self._load_vm_meta(source_meta_data)
        target_meta = self._load_target_meta(source_meta.copy(), action='import')
        self._verify_target_meta(target_meta)

        # Display action/meta information
        self._output('Importing a VM from remote backup "{0}" to a new VM named "{1}"'.format(remote_path, target_meta['name']))
        self._pprint_meta(source_meta, target_meta)

        # Confirm XML file exists
        self._output('Confirming XML file exists in remote directory: "{0}"'.format(remote_path), 2)
        command = self._remote_ssh_command(['test', '-f', '{0}/{1}'.format(remote_dir, source_meta['xml'])])
        if not self._execute(command, boolean=True):
            self._raise('The required XML file does not exist in remote directory: "{0}/{1}"'.format(remote_path, source_meta['xml']))

        # Confirm image file exists
        self._output('Confirming VM image file exists in remote directory: "{0}"'.format(remote_path), 2)
        command = self._remote_ssh_command(['test', '-f', '{0}/{1}'.format(remote_dir, source_meta['image'])])
        if not self._execute(command, boolean=True):
            self._raise('The required VM image file does not exist in remote directory: "{0}/{1}"'.format(remote_path, source_meta['image']))

        # Transfer remote XML to local file
        self._output('Loading remote XML and creating a temporary modified copy: "{0}/{1}"'.format(remote_path, source_meta['xml']), 2)
        command = self._remote_ssh_command(['cat', '{0}/{1}'.format(remote_dir, source_meta['xml'])])
        source_xml = self._execute(command)
        target_xml = self._load_target_xml(source_xml, source_meta, target_meta, action='import')

        target_xml_file = os.path.realpath('{0}-{1}.temp.xml'.format(target_meta['name'], self.now))
        self._write_file(target_xml_file, target_xml)

        # Resolve conflicts with existing VMs on the host machine
        potential_conflicts = [
            ('name', target_meta['name']),
            ('disk', target_meta['disk']),
            ('uuid', target_meta['uuid']),
            ('mac', target_meta['mac'])
        ]
        self._vm_resolve_conflicts(potential_conflicts)

        # Create logical volume
        self._lv_create(target_meta['logical_volume_size'], target_meta['logical_volume'], target_meta['volume_group'])

        # Transfer LV image with dd over ssh
        command_queue = []
        ssh_command = self._remote_ssh_command(['dd', 'bs={0}'.format(self.args.block_size), 'if={0}/{1}'.format(remote_dir, source_meta['image'])])
        command_queue.append(ssh_command)

        if source_meta['compression'] != 'none':
            zip_command = [str(source_meta['compression']), '-d']
            command_queue.append(zip_command)

        target_lv = '/dev/{0}/{1}'.format(target_meta['volume_group'], target_meta['logical_volume'])
        command_queue.append(['dd', 'bs={0}'.format(self.args.block_size), 'of={0}'.format(target_lv)])

        # Execute commands
        self._output('Importing VM disk image. This will take time.', show_timestamp=True)
        self._output('Starting remote VM image import.', 2)
        self._execute_queue(command_queue)
        self._output('Successfully completed remote VM image import.', 2)

        # Set return data dictionary and return data
        return_data['target_xml_file'] = target_xml_file
        return_data['target_name'] = target_meta['name']
        return return_data

    # --------------------------------------------------------------------------
    # Action function - Import Local
    # --------------------------------------------------------------------------
    def _import_local(self):
        '''
        Import a VM from a local backup image.
        '''
        self._output('Executing local import action', 2)

        # Create variables
        return_data = {}

        # Verify source directory exists
        source_directory = os.path.abspath(self.args.source)
        source_directory = source_directory.rstrip('/') + '/'
        if not os.path.exists(source_directory):
            self._raise('Could not find source directory: "{0}".'.format(source_directory))

        # Load and verify meta data
        self._output('Loading and verifying VM meta data', 2)
        source_meta_file = source_directory + 'meta.txt'
        source_meta = self._load_vm_meta_from_file(source_meta_file)
        target_meta = self._load_target_meta(source_meta.copy(), action='import')
        self._verify_target_meta(target_meta)

        # Display action/meta information
        self._output('Importing a VM from "{0}" to a local VM named "{1}"'.format(self.args.source, target_meta['name']))
        self._pprint_meta(source_meta, target_meta)

        # Verify source XML file exists and create temporary target XML
        self._output('Loading source XML and creating target XML', 2)
        source_xml_file = os.path.realpath(source_directory + source_meta['xml'])
        source_xml = self._read_file(source_xml_file)
        target_xml = self._load_target_xml(source_xml, source_meta, target_meta, action='import')

        target_xml_file = os.path.realpath('{0}-{1}.temp.xml'.format(target_meta['name'], self.now))
        self._write_file(target_xml_file, target_xml)

        # Resolve conflicts with existing VMs on the host machine
        potential_conflicts = [
            ('name', target_meta['name']),
            ('disk', target_meta['disk']),
            ('uuid', target_meta['uuid']),
            ('mac', target_meta['mac'])
        ]
        self._vm_resolve_conflicts(potential_conflicts)

        # Create logical volume
        self._lv_create(target_meta['logical_volume_size'], target_meta['logical_volume'], target_meta['volume_group'])

        # Copy backup image to new logical volume
        self._output('Importing VM disk image. This will take time.', show_timestamp=True)
        source_image_file = os.path.realpath(source_directory + target_meta['image'])
        self._lv_import(source_image_file, target_meta['disk'], compression=source_meta['compression'])

        # Set return data dictionary and return data
        return_data['target_xml_file'] = target_xml_file
        return_data['target_name'] = target_meta['name']
        return return_data

    # --------------------------------------------------------------------------
    # Action function - Clone
    # --------------------------------------------------------------------------
    def clone(self):
        '''
        Create a new VM based on a current VM. Default action is to load from a
        backup directory. The directory must include a meta file, XML file, and
        a VM disk image. If the --live argument is passed, the source will be a
        defined local VM instead of a backup directory.
        '''
        self._output('Starting Clone action.', 2)

        # Determine whether this is a live clone or clone from storage.
        if self.args.live:
            data = self._clone_live()
            success_message = 'Success: cloned VM from a live VM "{0}" to a VM named "{1}"'.format(data['source_name'], data['target_name'])
        elif self.args.remote:
            data = self._clone_remote()
            success_message = 'Success: cloned VM from a remote backup image "{0}" to a VM named "{1}"'.format(data['source_directory'], data['target_name'])
        else:
            data = self._clone_local()
            success_message = 'Success: cloned VM from a backup image "{0}" to a VM named "{1}"'.format(data['source_directory'], data['target_name'])

        # virsh define target_xml file
        self._vm_define(data['target_xml_file'])

        # Boot VM if argument has been passed
        if self.args.start:
            self._vm_start(data['target_name'])

        # Add new VM to autostart list if the autostart argument has been passed
        if self.args.autostart:
            self._vm_autostart(data['target_name'])

        # Remove temporary target_xml_file
        self._unlink_file(data['target_xml_file'])

        # Print success message and warning to change hostname
        self._output(success_message)
        self._output('\n**Note: Guest OS must still be configured, e.g. hostname, networking, etc still need to be configured.')

    # --------------------------------------------------------------------------
    # Action function - Clone live
    # --------------------------------------------------------------------------
    def _clone_live(self):
        '''
        Clone directly from a VM already on the Host OS.
        '''
        self._output('Executing live clone action', 2)

        # Create variables
        return_data = {}

        # Load and verify meta data
        self._output('Loading and verifying VM meta data', 2)
        source_meta = self._create_vm_meta(self.args.source)
        target_meta = self._load_target_meta(source_meta.copy(), action='clone')
        self._verify_target_meta(target_meta)

        # Display action/meta information
        self._output('Cloning a live VM "{0}" to a new VM named "{1}"'.format(self.args.source, self.args.name))
        self._pprint_meta(source_meta, target_meta)

        # Load source XML and create target XML
        self._output('Loading source XML and creating target XML', 2)
        source_xml = self.vm_info(source_meta['name'], 'xml')
        target_xml = self._load_target_xml(source_xml, source_meta, target_meta, action='clone')

        # Set snapshot variables
        if source_meta['disk_file']:
            source_path = source_meta['disk_file']
        else:
            source_path = source_meta['disk']
        initial_source_vm_status = self.vm_info(source_meta['name'], 'status')
        snapshot_name = '{0}.snapshot'.format(source_meta['name'])
        snapshot_path = '{0}.snapshot'.format(source_path)

        # If VM is running suspend it. Cache status for later.
        if initial_source_vm_status == 'running':
            self._vm_suspend(source_meta['name'])

        # Create a LV snapshot
        self._lv_create_snapshot(source_meta['name'], snapshot_name)

        # If VM was running (refer to cached variable), restart it.
        if initial_source_vm_status == 'running':
            self._vm_resume(source_meta['name'])

        # Resolve conflicts with existing VMs on the host machine
        potential_conflicts = [
            ('name', target_meta['name']),
            ('disk', target_meta['disk']),
            ('uuid', target_meta['uuid']),
            ('mac', target_meta['mac'])
        ]
        self._vm_resolve_conflicts(potential_conflicts)

        try:
            # Create target logical volume
            self._lv_create(target_meta['logical_volume_size'], target_meta['name'], target_meta['volume_group'])
            # Copy source LV snapshot to target LV
            # Wrapped in a try/except decorator, don't handle exception here.
            self._output('Cloning VM disk image. This will take time.', show_timestamp=True)
            self._lv_import(snapshot_path, target_meta['disk'])
        finally:
            # Remove LV snapshot
            # If either LV action fails we ensure the LV snapshot is removed,
            # preventing an unstable scenario when running from an unmonitored
            # terminal (such as a backup script on a cron job).
            self._lv_remove(snapshot_path)

        # Save target_xml to a temporary file
        target_xml_file = os.path.realpath('./target_xml_{0}.tmp'.format(self.now))
        self._write_file(target_xml_file, target_xml)

        # Set return data dictionary and return data
        if source_meta['disk_file']:
            return_data['source_directory'] = source_meta['disk_file']
        else:
            return_data['source_directory'] = source_meta['disk']
        return_data['source_name'] = source_meta['name']
        return_data['target_name'] = target_meta['name']
        return_data['target_xml_file'] = target_xml_file
        return return_data

    # --------------------------------------------------------------------------
    # Action function - Clone remote
    # --------------------------------------------------------------------------
    def _clone_remote(self):
        '''
        Clone from a remote backup image over ssh.
        '''
        self._output('Executing remote clone action', 2)

        # Set variables
        return_data = {}
        remote_address = self.args.remote
        remote_dir = self.args.source
        remote_path = '{0}:{1}'.format(remote_address, remote_dir)

        # Confirm meta.txt file exists
        self._output('Confirming meta.txt file exists in remote directory: "{0}"'.format(remote_path), 2)
        command = self._remote_ssh_command(['test', '-f', '{0}/meta.txt'.format(remote_dir)])
        if not self._execute(command, boolean=True):
            self._raise('The required meta.txt file does not exist in remote directory: "{0}"'.format(remote_path))

        # Return and parse remote meta.txt
        self._output('Retrieving meta.txt file data from remote directory: "{0}"'.format(remote_path), 2)
        command = self._remote_ssh_command(['cat', '{0}/meta.txt'.format(remote_dir)])
        source_meta_data = self._execute(command)
        source_meta = self._load_vm_meta(source_meta_data)
        target_meta = self._load_target_meta(source_meta.copy(), action='clone')
        self._verify_target_meta(target_meta)

        # Display action/meta information
        self._output('Cloning a VM from a remote backup in "{0}" to a new VM named "{1}"'.format(remote_path, self.args.name))
        self._pprint_meta(source_meta, target_meta)

        # Confirm XML file exists
        self._output('Confirming XML file exists in remote directory: "{0}"'.format(remote_path), 2)
        command = self._remote_ssh_command(['test', '-f', '{0}/{1}'.format(remote_dir, source_meta['xml'])])
        if not self._execute(command, boolean=True):
            self._raise('The required XML file does not exist in remote directory: "{0}/{1}"'.format(remote_path, source_meta['xml']))

        # Confirm image file exists
        self._output('Confirming VM image file exists in remote directory: "{0}"'.format(remote_path), 2)
        command = self._remote_ssh_command(['test', '-f', '{0}/{1}'.format(remote_dir, source_meta['image'])])
        if not self._execute(command, boolean=True):
            self._raise('The required VM image file does not exist in remote directory: "{0}/{1}"'.format(remote_path, source_meta['image']))

        # Transfer remote XML to local file
        self._output('Loading remote XML and creating a temporary modified copy: "{0}/{1}"'.format(remote_path, source_meta['xml']), 2)
        command = self._remote_ssh_command(['cat', '{0}/{1}'.format(remote_dir, source_meta['xml'])])
        source_xml = self._execute(command)
        target_xml = self._load_target_xml(source_xml, source_meta, target_meta, action='clone')

        target_xml_file = os.path.realpath('{0}-{1}.temp.xml'.format(target_meta['name'], self.now))
        self._write_file(target_xml_file, target_xml)

        # Resolve conflicts with existing VMs on the host machine
        potential_conflicts = [
            ('name', target_meta['name']),
            ('disk', target_meta['disk']),
            ('uuid', target_meta['uuid']),
            ('mac', target_meta['mac'])
        ]
        self._vm_resolve_conflicts(potential_conflicts)

        # Create logical volume
        self._lv_create(target_meta['logical_volume_size'], target_meta['logical_volume'], target_meta['volume_group'])

        # Transfer LV image with dd over ssh
        command_queue = []
        ssh_command = self._remote_ssh_command(['dd', 'bs={0}'.format(self.args.block_size), 'if={0}/{1}'.format(remote_dir, source_meta['image'])])
        command_queue.append(ssh_command)

        if source_meta['compression'] != 'none':
            zip_command = [str(source_meta['compression']), '-d']
            command_queue.append(zip_command)

        target_lv = '/dev/{0}/{1}'.format(target_meta['volume_group'], target_meta['logical_volume'])
        command_queue.append(['dd', 'bs={0}'.format(self.args.block_size), 'of={0}'.format(target_lv)])

        # Execute commands
        self._output('Cloning VM disk image. This will take time.', show_timestamp=True)
        self._output('Starting remote VM image import.', 2)
        self._execute_queue(command_queue)
        self._output('Successfully completed remote VM image import.', 2)

        # Set return data dictionary and return data
        return_data['source_directory'] = remote_path
        return_data['source_name'] = source_meta['name']
        return_data['target_xml_file'] = target_xml_file
        return_data['target_name'] = target_meta['name']
        return return_data

    # --------------------------------------------------------------------------
    # Action function - Clone local
    # --------------------------------------------------------------------------
    def _clone_local(self):
        '''
        Import a VM from a local backup VM image.
        '''
        self._output('Executing local clone action', 2)

        # Create variables
        return_data = {}

        # Verify source directory exists
        source_directory = os.path.abspath(self.args.source)
        source_directory = source_directory.rstrip('/') + '/'
        if not os.path.exists(source_directory):
            self._raise('Could not find source directory: "{0}".'.format(source_directory))

        # Load and verify meta data
        self._output('Loading and verifying VM meta data', 2)
        source_meta_file = source_directory + 'meta.txt'
        source_meta = self._load_vm_meta_from_file(source_meta_file)
        target_meta = self._load_target_meta(source_meta.copy(), action='clone')
        self._verify_target_meta(target_meta)

        # Display action/meta information
        self._output('Cloning a VM from a backup in "{0}" to a new VM named "{1}"'.format(self.args.source, self.args.name))
        self._pprint_meta(source_meta, target_meta)

        # Load source XML and create target XML
        self._output('Loading source XML and creating target XML', 2)
        source_xml_file = os.path.realpath(source_directory + source_meta['xml'])
        source_xml = self._read_file(source_xml_file)
        target_xml = self._load_target_xml(source_xml, source_meta, target_meta, action='clone')

        # Resolve conflicts with existing VMs on the host machine
        potential_conflicts = [
            ('name', target_meta['name']),
            ('disk', target_meta['disk']),
            ('uuid', target_meta['uuid']),
            ('mac', target_meta['mac'])
        ]
        self._vm_resolve_conflicts(potential_conflicts)

        # Create logical volume
        self._lv_create(target_meta['logical_volume_size'], target_meta['name'], target_meta['volume_group'])

        # Copy backup image to new logical volume
        self._output('Cloning VM disk image. This will take time.', show_timestamp=True)
        source_image_file = os.path.realpath(source_directory + source_meta['image'])
        self._lv_import(source_image_file, target_meta['disk'], compression=target_meta['compression'])

        # Save target_xml to a temporary file
        target_xml_file = os.path.realpath(source_directory + 'target_xml_{0}.tmp'.format(self.now))
        self._write_file(target_xml_file, target_xml)

        # Set return data dictionary and return data
        return_data['source_directory'] = source_directory
        return_data['source_name'] = source_meta['name']
        return_data['target_name'] = target_meta['name']
        return_data['target_xml_file'] = target_xml_file
        return return_data

    # --------------------------------------------------------------------------
    # Action general utility functions
    # --------------------------------------------------------------------------
    def _return_json(self, data, pprint=False):
        '''
        Take a native python datatype and return encoded JSON
        '''
        # Encode values and return them
        try:
            if pprint:
                encoder = json.JSONEncoder(True, True, True, True, False, 4)
            else:
                encoder = json.JSONEncoder(False, True, True, True, False, 4)
            return encoder.encode(data)
        except IOError, e:
            self._raise(e, 'Could not encode data into JSON.')

    def _read_file(self, path):
        '''
        Simple try/except wrapper for reading file contents.
        '''
        self._output('Reading file: "{0}"'.format(path), 3)
        try:
            fh = open(path, 'r')
            data = fh.read()
            fh.close()
        except IOError, e:
            self._raise(e, 'Could not read file: "{0}"'.format(path))
        return data

    def _write_file(self, path, data, mode='w+'):
        '''
        Simple try/except wrapper for writing to a file.
        '''
        self._output('Writing data to file: "{0}"'.format(path), 3)
        try:
            fh = open(path, mode)
            fh.write(data)
            fh.close()
        except IOError, e:
            self._raise(e, 'Could not write file: "{0}" Mode: "{1}'.format(path, mode))

    def _unlink_file(self, path):
        '''
        Simple try/except wrapper for unlinking (removing) a file.
        '''
        self._output('Unlinking (removing) file: "{0}"'.format(path), 3)
        try:
            return os.unlink(path)
        except IOError, e:
            self._raise(e, 'Could not unlink (remove) file: "{0}"'.format(path))

    def _create_mac_address(self, unique=False):
        '''
        Return bridge MAC address in the 52:54:00:XX:XX:XX range. The unique
        argument tests if the MAC address is already defined in another VM.
        If so it will regenerate and test again based on the number of VMs
        defined on the host machine.
        '''
        attempts = (self.vm_count() * 50) + 1
        for i in range(attempts, 0, -1):
            address_list = [0x52, 0x54, 0x00, random.randint(0x00, 0x7f), random.randint(0x00, 0xff), random.randint(0x00, 0xff)]
            address = ':'.join(['%02x' % x for x in address_list])
            if self.vm_info_is_unique('mac', address, raise_exception=False):
                return address
            if i == 1:
                self._raise('Could not generated a unique MAC address. Tried {0} attempts.'.format(attempts))

    def _remote_ssh_command(self, remote_command):
        '''
        Return a self._execute() ready command. Keeps identity file logic in
        one location.
        '''
        ssh_command = ['ssh', '{0}'.format(self.args.remote)]
        if self.args.identity_file:
            ssh_command[1:1] = ['-i', '{0}'.format(self.args.identity_file)]
        command = ssh_command + remote_command
        return command

    def _remote_source_scp_command(self, source, target):
        '''
        Return a self._execute() ready command. Keeps identity file logic in
        one location.
        '''
        source = '{0}:{1}'.format(self.args.remote, source)
        command = ['scp', source, target]
        if self.args.identity_file:
            command[1:1] = ['-i', '{0}'.format(self.args.identity_file)]
        return command

    def _remote_target_scp_command(self, source, target):
        '''
        Return a self._execute() ready command. Keeps identity file logic in
        one location.
        '''
        target = '{0}:{1}'.format(self.args.remote, target)
        command = ['scp', source, target]
        if self.args.identity_file:
            command[1:1] = ['-i', '{0}'.format(self.args.identity_file)]
        return command

    # --------------------------------------------------------------------------
    # Application utility functions
    # --------------------------------------------------------------------------
    @execute_safely
    def _execute(self, command, stdin=None, stdout=None, stderr=None, boolean=False, output_level=2):
        '''
        Execute a command on the system. Return stdout on success, raise
        an exception on failure, and log result in either case. If boolean is True,
        return the boolean value based on system exit code (zero:True, non-zero:False)
        and do not log any results.
        '''
        # Verify passed arguments
        if not type(command) is list or len(command) == 0:
            self._raise('Execute method received invalid command argument. Should receive a list containing each command token as a string. Instead received: "{0}"'.format(command))

        # Setup command
        named_args = { 'stdout':subprocess.PIPE, 'stderr':subprocess.PIPE }
        if stdin:
            named_args['stdin'] = stdin
        if stdout:
            named_args['stdout'] = stdout
        if stderr:
            named_args['stderr'] = stderr

        # Print command to output
        command_string = ' '.join(command)
        self._output('Executing command: `{0}`'.format(command_string), output_level)

        # Initiate process and listen for completion. Determine success from
        # return code
        process = subprocess.Popen(command, **named_args)
        stdout, stderr = process.communicate()
        is_success = (process.returncode == 0)

        # Log history if boolean is False
        history = not boolean
        if history and is_success:
            self._history('success', 'Command: {0} | Stdout: {1}'.format(command_string, stdout))
        elif history and not is_success:
            self._history('error', 'Command: {0} | Stdout: {1}'.format(command_string, stdout))

        # Return a boolean if requested
        if boolean:
            return is_success

        # Otherwise return stdout on success and raise an error on failure.
        if is_success:
            return stdout
        else:
            self._raise('Stdout: {0} | Stderr: {1}'.format(stdout, stderr))

    @execute_safely
    def _execute_queue(self, commands, boolean=False, output_level=2):
        '''
        Execute multiple piped commands on the system. The argument commands
        should be a list containing a sublist for each command. The order of the
        list determines the order of the command: commands[0] | commands[1] |
        [...] | commands[n-1] | commands[n].
        Return stdout on success, raise an exception on failure, and log result
        in either case. If boolean is True, return the boolean value based on
        system exit code (zero:True, non-zero:False) and do not log any results.
        '''
        # Verify passed arguments
        if not type(commands) is list or len(commands) == 0:
            self._raise('Execute queue method received invalid commands argument. Should receive a list containing a sublist for each command. Instead received: "{0}"'.format(commands))

        # Create process pipes
        previous_command = None
        for command in commands:
            named_args = {'stdout':subprocess.PIPE, 'stderr':subprocess.PIPE}
            if previous_command:
                named_args['stdin'] = previous_command.stdout
            previous_command = subprocess.Popen(command, **named_args)

        # Print command to output
        command_string = ' | '.join([' '.join(command) for command in commands])
        self._output('Executing command: `{0}`'.format(command_string), output_level)

        # Set post process variables
        stdout, stderr = previous_command.communicate()
        is_success = (previous_command.returncode == 0)

        # Log history if boolean is False
        history = not boolean
        if history and is_success:
            self._history('success', 'Command: {0} | Stdout: {1}'.format(command_string, stdout))
        elif history and not is_success:
            self._history('error', 'Command: {0} | Stdout: {1}'.format(command_string, stdout))

        # Return a boolean if requested
        if boolean:
            return is_success

        # Otherwise return stdout on success and raise an error on failure.
        if is_success:
            return stdout
        else:
            self._raise('Stdout: {0} | Stderr: {1}'.format(stdout, stderr))

    def _output(self, message, message_level=1, show_timestamp=False):
        '''
        Control stdout IO with greater granularity. All calls are printed to
        standard out. They are not logged in any file. Only calls to
        self._history() and self._raise() are saved to the error and log files.
        '''
        # Determine output level based on command line argument.
        # Default to output level 1 if arg parsing is not yet complete.
        try:
            output_level = int(self.args.output_level)
        except AttributeError:
            output_level = 1
        if output_level > 1 or show_timestamp:
            timestamp = '[' + str(datetime.now()) + ']'
        else:
            timestamp = ''

        # Always display messages with message_level 0. If not 0,
        # check against dynamic command line argument --output-level
        if message_level == 0 or message_level <= output_level:
            print(timestamp + ' ' + message)

    def _history(self, key, value):
        '''
        Log command history for status and error logs.
        '''
        self.status['command_history'].append((str(datetime.now()), key, value))

    def _raise(self, *errors, **kwargs):
        '''
        Simple wrapper to raising an ApplicationError. Flexible number of args
        are allowed. Each argument is turned to its str() representation and
        joined on a common separator ' | '. Finally, the error is raised with
        the combined error string. Errors are saved to log and error files,
        as well as printed to the standard out (see sys_exit decorator).
        '''
        tostring = [str(e) for e in errors]
        message = ' | '.join(tostring)
        raise ApplicationError(message)

# ==============================================================================
# Init
# ==============================================================================
if __name__ == '__main__':
    Vmpy()
else:
    print('Error: Command line support only')
    sys.exit(1)
