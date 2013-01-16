#!/bin/bash

# Basic functionality testing for vm.py.

# Warning: even for small disk images these will take between 15-30 minutes 
# to complete depending on the task. Take this into consideration before 
# calling each function!

# Test variables

REMOTE_ADDR="laskey@agis.chrislaskey.com"
REMOTE_IDENTITY_FILE="/home/laskey/.ssh/virtual-machines"
REMOTE_ARGUMENT="--remote ${REMOTE_ADDR} -i ${REMOTE_IDENTITY_FILE}"
REMOTE_PATH="/www/vm-storage/testing-min/20120708-0610" # TODO: Complete date before testing
LOCAL_PATH="/vm-storage/testing-min/20120708-0637" # TODO: Complete date before testing

COMMAND_BACKUP_LOCAL="./vm.py backup testing-min /vm-storage"
COMMAND_BACKUP_REMOTE="./vm.py backup ${REMOTE_ARGUMENT} testing-min ${REMOTE_PATH}"
COMMAND_IMPORT_LOCAL="./vm.py import ${LOCAL_PATH} om-import-local"
COMMAND_IMPORT_LOCAL_TESTING_MIN="./vm.py import ${LOCAL_PATH}"
COMMAND_IMPORT_REMOTE="./vm.py import ${REMOTE_ARGUMENT}  --autostart --no-boot --bridge br1 --logical-volume om-import-local ${REMOTE_PATH} om-import-remote"
COMMAND_CLONE_LIVE="./vm.py clone --live testing-min om-clone-live"
COMMAND_CLONE_LOCAL="./vm.py clone /vm-storage/testing-min/20120708-0637 om-clone-local"
COMMAND_CLONE_REMOTE="./vm.py clone ${REMOTE_ARGUMENT} ${REMOTE_PATH} om-clone-remote"

# Test functions

test_local_backup () {
	echo 'Executing local backup command'
	$COMMAND_BACKUP_LOCAL
	if [[ $? == 0 ]]; then
		echo 'Completed local backup command'
	else
		echo 'Error executing local backup command'
		exit 2
	fi
}

test_remote_backup () {
	echo 'Executing remote backup command'
	$COMMAND_BACKUP_REMOTE
	if [[ $? == 0 ]]; then
		echo 'Completed remote backup command'
	else
		echo 'Error executing remote backup command'
		exit 2
	fi
}

test_local_import () {
	echo 'Executing local import command'
	$COMMAND_IMPORT_LOCAL
	if [[ $? == 0 ]]; then
		echo 'Completed local import command'
	else
		echo 'Error executing local import command'
		exit 2
	fi
}

test_local_import_with_absolute_minimum_command () {
	echo 'Executing local import testing min command'
	$COMMAND_IMPORT_LOCAL_TESTING_MIN
	if [[ $? == 0 ]]; then
		echo 'Completed local import testing min command'
	else
		echo 'Error executing local import testing min command'
		exit 2
	fi
}

test_remote_import () {
	echo 'Executing remote import command'
	$COMMAND_IMPORT_REMOTE
	if [[ $? == 0 ]]; then
		echo 'Completed remote import command'
	else
		echo 'Error executing remote import command'
		exit 2
	fi
}

test_live_clone () {
	echo 'Executing live clone command'
	$COMMAND_CLONE_LIVE
	if [[ $? == 0 ]]; then
		echo 'Completed live clone command'
	else
		echo 'Error executing live clone command'
		exit 2
	fi
}


test_local_clone () {
	echo 'Executing local clone command'
	$COMMAND_CLONE_LOCAL
	if [[ $? == 0 ]]; then
		echo 'Completed local clone command'
	else
		echo 'Error executing local clone command'
		exit 2
	fi
}

test_remote_clone () {
	echo 'Executing remote clone command'
	$COMMAND_CLONE_REMOTE
	if [[ $? == 0 ]]; then
		echo 'Completed remote clone command'
	else
		echo 'Error executing remote clone command'
		exit 2
	fi
}

# Testing

# test_local_backup
# test_remote_backup
# test_local_import
# test_local_import_with_absolute_minimum_command
# test_remote_import
# test_live_clone
# test_local_clone
# test_remote_clone
