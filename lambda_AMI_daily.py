import boto3
import collections
import datetime
import sys
import pprint
import time

ec = boto3.client('ec2')
asg = boto3.client('autoscaling')

def lambda_handler(event, context):
    reservations = ec.describe_instances(
        Filters=[
            {'Name': 'tag-key', 'Values': ['Backup', 'backup']},
            {'Name': 'tag-value', 'Values': ['Daily', 'daily']},
        ]
    ).get(
        'Reservations', []
    )

    instances = sum(
        [
            [i for i in r['Instances']]
            for r in reservations
        ], [])

    print "Found %d instances that need a daily back up" % len(instances)

    to_tag = collections.defaultdict(list)
    device = collections.defaultdict(list)
    names = collections.defaultdict(list)
    
    for instance in instances:
        try:
            retention_days = [
                int(t.get('Value')) for t in instance['Tags']
                if t['Key'] == 'Retention'][0]
        except IndexError:
            retention_days = 1
            
        name = [
            str(t.get('Value')) for t in instance['Tags']
            if t['Key'] == 'Name']
            
        name = str(name)
        name = name.strip( "[']" )

        desc = [
            str(t.get('Value')) for t in instance['Tags']
            if t['Key'] == 'Description']
            
        desc = str(desc)
        desc = desc.strip( "[']" )

        #for dev in instance['BlockDeviceMappings']:
        #    dev_name = str(dev.get('DeviceName'))
        #    if dev.get('Ebs', None) is None:
        #        continue
        #    vol_id = dev['Ebs']['VolumeId']
        #    print "Found EBS volume %s named %s on instance %s" % (
        #        vol_id, dev_name, instance['InstanceId'])

        #    snap = ec.create_snapshot(
        #        VolumeId=vol_id, Description="Weekly Backup - View DeviceName and DeleteOn Tags - " + desc
        #    )
        
        create_time = datetime.datetime.now()
        create_fmt = create_time.strftime('%Y-%m-%d')
            
        AMIid = ec.create_image(InstanceId=instance['InstanceId'], Name="AMI - " + name + " from " + create_fmt, Description="AMI Backup of instance " + instance['InstanceId'] + " from " + create_fmt, NoReboot=True, DryRun=False)
            
        #pprint.pprint(instance)
            
        to_tag[retention_days].append(AMIid['ImageId'])

        print "Retaining AMI %s of instance %s for %d days" % (

            AMIid['ImageId'],
            instance['InstanceId'],
            retention_days,

        )
        
        print to_tag.keys()
            
        for retention_days in to_tag.keys():
            delete_date = datetime.date.today() + datetime.timedelta(days=retention_days)
            delete_fmt = delete_date.strftime('%Y-%m-%d')
            print "Will delete %d AMIs on %s" % (len(to_tag[retention_days]), delete_fmt)
            ec.create_tags(
                Resources=to_tag[retention_days],
                Tags=[
                    {'Key': 'DeleteOn', 'Value': delete_fmt},
                ]
            )
            
        #    to_tag[retention_days].append(snap['SnapshotId'])
        #    device[dev_name].append(snap['SnapshotId'])
        #    names[name].append(snap['SnapshotId'])
            
        #    ec.create_tags(
        #    Resources=device[dev_name],
        #    Tags=[
        #        {'Key': 'DeviceName', 'Value': dev_name},
        #        ]
        #    )
            
        #    ec.create_tags(
        #    Resources=names[name],
        #    Tags=[
        #        {'Key': 'Name', 'Value': name},
        #        ]
        #    )
            
        #    print "Retaining snapshot %s of volume %s from instance %s for %d days" % (
        #        snap['SnapshotId'],
        #        vol_id,
        #        instance['InstanceId'],
        #        retention_days,
        #    )
        
        # Check if instance is in an ASG already, filter by name of target ASG
        try:
            instanceASG = asg.describe_auto_scaling_instances(InstanceIds=[instance['InstanceId']])['AutoScalingInstances'][0]['AutoScalingGroupName']
            
            # Get ASG name
            #asgName = instanceASG['AutoScalingInstances'][0]['AutoScalingGroupName']
            
            
            # Get old launch configuration (to be deleted)
            oldLC = asg.describe_auto_scaling_groups(AutoScalingGroupNames=[instanceASG])['AutoScalingGroups'][0]['LaunchConfigurationName']
            #print oldLC
            
            # create LC using instance from target ASG as a template, only diff is the name of the new LC and new AMI
            timeStamp = time.time()
            timeStampString = datetime.datetime.fromtimestamp(timeStamp).strftime('%Y-%m-%d')
            newLaunchConfigName = name + '-LC ' + AMIid['ImageId'] + ' ' + timeStampString
            asg.create_launch_configuration(
                InstanceId = instance['InstanceId'],
                LaunchConfigurationName = newLaunchConfigName,
                ImageId= AMIid['ImageId'] )
                
            # update ASG to use new LC
            asg.update_auto_scaling_group(AutoScalingGroupName = instanceASG,LaunchConfigurationName = newLaunchConfigName)
            
            # delete old LC
            asg.delete_launch_configuration(LaunchConfigurationName = oldLC)
            
            print 'Updated ASG `%s` with new launch configuration `%s` which includes AMI `%s`.' % (instanceASG, newLaunchConfigName, AMIid['ImageId'])
        
        except:
            print 'No ASG for ' + name + ', continuing backup'