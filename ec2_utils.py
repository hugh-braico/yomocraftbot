import os
import logging
import boto3
from pprint import pformat
from botocore.exceptions import ClientError

log = logging.getLogger("bot")

ec2 = boto3.client('ec2')

# boto3 reads the AWS credentials from environment variables automatically,
# so we only need the info about the EC2 instance.
EC2_INSTANCE_ID = os.getenv('EC2_INSTANCE_ID')
	

# Get the current state of the instance
# one of 'pending'|'running'|'shutting-down'|'terminated'|'stopping'|'stopped'
def get_ec2_status():
	log.info(f"get_ec2_status: checking status of {EC2_INSTANCE_ID}...")
	resp = ec2.describe_instances(InstanceIds=[EC2_INSTANCE_ID])
	return resp['Reservations'][0]['Instances'][0]['State']['Name']


# Start the instance
def start_ec2_instance():
	log.info(f"start_ec2_instance: starting instance {EC2_INSTANCE_ID}...")
	ec2.start_instances(InstanceIds=[EC2_INSTANCE_ID])


# Stop the instance
def stop_ec2_instance():
	log.info(f"stop_ec2_instance: stopping instance {EC2_INSTANCE_ID}...")
	ec2.stop_instances(InstanceIds=[EC2_INSTANCE_ID])