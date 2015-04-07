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

IGNORED_MOUNTS = [
  "df-run",
  "df-dev"
]

IGNORED_HOSTS = [
  "staging.ofertia.com",
  "testing.ofertia.com"
]

DOMAINS = {
  'se': 'bonial.se',
  'dk': 'bonial.dk',
  'no': 'bonial.no',
  'es': 'ofertia.com',
  'mx': 'ofertia.com.mx',
  'co': 'ofertia.com.co',
  'cl': 'ofertia.cl',
  'me': 'mesos'
}


def getServerInfo(name):
  pattern="^(\w{2})(-\w+-\d)_?(\w+_\w+)?"
  result = re.match(pattern, name)
  if not result:
    server = name.replace("_",".")
    domain = server
  else:
    country = result.group(1)
    server = "%s%s" % (result.group(1), result.group(2))
    domain = DOMAINS[country]

  return server,domain
  
def FormatMountPoinName(name):
  return "/"+name[3:].replace("-","/")

def AddServiceCheck(service, instance, name, metric, check_type, value, debounce=0, frequency=1, expected_num_hosts=1):
  """
  Create check for metric, and add to service
  """
  check, bCreated = GraphiteStatusCheck.objects.get_or_create(
      name = name,
      metric = metric,
      defaults = {
        "check_type": check_type,
        "value": value,
        "created_by_id": 2,
        "importance": Service.ERROR_STATUS,
        "frequency": frequency,
        "debounce": debounce,
        "expected_num_hosts": expected_num_hosts,
        }
  )
  service.status_checks.add(check);
  instance.status_checks.add(check);

class Command(BaseCommand):
  def handle(self, *args, **options):
    user = User.objects.get(username="admin");

    servers = dict()
    # search for all servers
    metrics = get_matching_metrics("servers.*"); 
    for metric in metrics["metrics"]:
      print metric
      server, domain = getServerInfo(metric['name'])
      if server == domain:
        address = server
        service_url = server
      else:
        address = server
        service_url = "www."+domain

      server_path = metric["path"]
      print server, domain, service_url, server_path

      # get or create service
      service, created = Service.objects.get_or_create(name=domain, defaults={"email_alert": True, "hipchat_alert": False})
      service.users_to_notify.add(user)

      # get or create instance
      instance, instance_created = Instance.objects.get_or_create(name=server, defaults={"address": address, "email_alert": True, "hipchat_alert": False, })
      instance.users_to_notify.add(user)
      service.instances.add(instance)

      # find all disks and add a check for percent free less then 5%
      disk_metrics = get_matching_metrics("%s.df.*" % (server_path)); # servers.www01.diskspace.root.gigabyte_percentfree     
      for disk_metric in disk_metrics["metrics"]:
        name, metric = FormatMountPoinName(disk_metric["name"]), disk_metric["path"]
        if any(v in name for v in IGNORED_MOUNTS): continue
        print name,metric
        AddServiceCheck(service, instance, 
          "%s disk %s" % (server, name), 
          "asPercent(%sfree,sumSeries(%s*))" % (metric, metric), 
          "<", 
          "15.0");

      # Add check for load over
      num_cpu = float(len(get_matching_metrics("%scpu-*" % (server_path))["metrics"]))
      AddServiceCheck(service, instance, 
        "%s load" % (server, ), 
        "%sload.load.midterm" % (server_path, ), 
        ">", 
        num_cpu);

      # Add check for memory
      AddServiceCheck(service, instance, 
        "%s low mem" % (server, ), 
        "asPercent(sumSeries(%smemory.{memory-cached,memory-free}),sumSeries(%smemory.*))"% (server_path, server_path),
        "<", 
        "10",
        frequency=5,
        debounce=6,
      );
