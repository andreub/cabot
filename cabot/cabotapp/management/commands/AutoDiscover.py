"""
Auto Discover proof of concept for Cabot
To use copy to cabot\cabotapp\management\commands\AutoDiscover.py
Run with this command: sh -ac ' . ./conf/production.env; python manage.py AutoDiscover'
"""
from django.core.management.base import BaseCommand
from django.contrib.auth.models import User

from cabot.cabotapp.models import *
from cabot.cabotapp.graphite import *
import re

IGNORED_MOUNTS =(
  "df-run",
  "df-dev"
)

def isValidHost(name):
  regexp=re.compile(".*(_\w)+")
  return regexp.match(name)
  
def FormatMountPoinName(name):
  return "/"+name[3:].replace("-","/")

def AddServiceCheck(instance, name, metric, check_type, value, debounce=0):
  """
  Create check for metric, and add to service
  """
  check, bCreated = GraphiteStatusCheck.objects.get_or_create(
      name = name,
      metric = metric,
      defaults = {
        "check_type": check_type,
        "value": value,
        "created_by_id": 2,  # hard coded to user 1
        "importance": Service.ERROR_STATUS,
        }
  )
  instance.status_checks.add(check);

class Command(BaseCommand):
  def handle(self, *args, **options):
    user = User.objects.get(username="admin");

    # search for all servers
    metrics = get_matching_metrics("servers.*"); 
    for metric in metrics["metrics"]:
      if not isValidHost(metric["name"]): continue
      server, domain  = metric["name"].split("_",1)
      domain = domain.replace("_",".")
      server_path = metric["path"]
      print server, domain, server_path

      # get or create service
      service, created = Service.objects.get_or_create(name=domain, defaults={"email_alert": True, "hipchat_alert": False})
      service.users_to_notify.add(user)

      # get or create instance
      instance, instance_created = Instance.objects.get_or_create(name=server, defaults={"address": ".".join((server,domain)), "email_alert": True, "hipchat_alert": False, })
      instance.users_to_notify.add(user)
      service.instances.add(instance)

      # find all disks and add a check for percent free less then 5%
      disk_metrics = get_matching_metrics("%s.df.*" % (server_path)); # servers.www01.diskspace.root.gigabyte_percentfree     
      for disk_metric in disk_metrics["metrics"]:
        name, metric = FormatMountPoinName(disk_metric["name"]), disk_metric["path"]
        if any(v in name for v in IGNORED_MOUNTS): continue
        print name,metric
        AddServiceCheck(instance, 
          "%s disk %s" % (server, name), 
          "asPercent(%sfree,sumSeries(%s*))" % (metric, metric), 
          "<", 
          "15.0");

      # Add check for load over 5
      num_cpu = float(len(get_matching_metrics("%scpu-*" % (server_path))["metrics"]))
      AddServiceCheck(instance, 
        "%s load" % (server, ), 
        "%sload.load.midterm" % (server_path, ), 
        ">", 
        num_cpu);

      # Add check for low swap+free  memory
      #AddServiceCheck(service, "%s low mem" % (server, ), "sumSeries(%smemory.SwapFree, %smemory.MemFree)"% (server_path, server_path), "<", "1000000");
