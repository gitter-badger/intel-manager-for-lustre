
# ==============================
# Copyright 2011 Whamcloud, Inc.
# ==============================

from django.db import models
from configure.models.jobs import StatefulObject, Job
from configure.lib.job import StateChangeJob, DependOn, DependAll, Step
from monitor.models import MeasuredEntity, DeletableDowncastableMetaclass, DowncastMetaclass

class DeletableStatefulObject(StatefulObject):
    """Use this class to create your own downcastable classes if you need to override 'save', because
    using the metaclass directly will override your own save method"""
    __metaclass__ = DeletableDowncastableMetaclass

    class Meta:
        abstract = True
        app_label = 'configure'

class ManagedHost(DeletableStatefulObject, MeasuredEntity):
    # FIXME: either need to make address non-unique, or need to
    # associate objects with a child object, because there
    # can be multiple servers on one hostname, eg ddn10ke

    # A URI like ssh://user@flint02:22/
    address = models.CharField(max_length = 255, unique = True)

    # A fully qualified domain name like flint02.testnet
    fqdn = models.CharField(max_length = 255, blank = True, null = True, unique = True)

    # TODO: separate the LNET state [unloaded, down, up] from the host state [created, removed]
    states = ['unconfigured', 'lnet_unloaded', 'lnet_down', 'lnet_up', 'removed']
    initial_state = 'unconfigured'

    DEFAULT_USERNAME = 'root'

    class Meta:
        app_label = 'configure'
        unique_together = ('address',)

    def __str__(self):
        return self.pretty_name()

    def save(self, *args, **kwargs):
        from django.core.exceptions import ValidationError
        MIN_LENGTH = 1
        if len(self.address) < MIN_LENGTH:
            raise ValidationError("Address '%s' is too short" % self.address)

        super(ManagedHost, self).save(*args, **kwargs)

    def to_dict(self):
        from django.contrib.contenttypes.models import ContentType
        return {'id' : self.id,
                'content_type_id': ContentType.objects.get_for_model(self.__class__).pk,
                'pretty_name': self.pretty_name(),
                'host_address' : self.address,
                'failnode':'',
                'kind' : self.role() ,
                'lnet_status' : str(self.state),
                'lnet_states': self.states, 
                'status':self.status_string()}

    @classmethod
    def create_from_string(cls, address_string, virtual_machine = None):
        from django.db import transaction

        # Single transaction for creating Host and related database objects
        # * Firstly because we don't want any of these unless they're all setup
        # * Secondly because we want them committed before creating any Jobs which
        #   will try to use them.
        with transaction.commit_on_success():
            host, created = ManagedHost.objects.get_or_create(address = address_string)
            monitor, created = Monitor.objects.get_or_create(host = host)
            lnet_configuration,created = LNetConfiguration.objects.get_or_create(host = host)

            from configure.lib.storage_plugin.manager import storage_plugin_manager
            storage_plugin_manager.create_root_resource('linux',
                    'HydraHostProxy', host_id = host.pk,
                    virtual_machine = virtual_machine)

        print "%s %s %s" % (host.pk, monitor.pk, lnet_configuration.pk)

        # Attempt some initial setup jobs
        from configure.lib.state_manager import StateManager
        StateManager().set_state(host, 'lnet_unloaded')
        StateManager().set_state(lnet_configuration, 'nids_known')

        return host

    def pretty_name(self):
        # Take FQDN if we have it, or fall back to address
        if self.fqdn:
            name = self.fqdn
        else:
            user, host, port = self.ssh_params()
            name = host

        if name[-12:] == ".localdomain":
            return name[:-12]
        else:
            return name
    
    def _role_strings(self):
        roles = set()
        for mountable in self.managedtargetmount_set.all():
            target = mountable.target.downcast()
            roles.add(target.role())

            #if isinstance(mountable, Client):
            #    roles.add("Client")

        #if self.router_set.count() > 0:
        #    roles.add("Router")

        return roles

    def is_unused(self):
        return (len(self._role_strings()) == 0)

    def is_mgs(self):
        from configure.models.target import ManagedMgs
        try:
            ManagedMgs.objects.get(managedtargetmount__host = self)
            return True
        except ManagedMgs.DoesNotExist:
            return False

    def available_lun_nodes(self):
        from django.db.models import Q
        from configure.models.target_mount import ManagedTargetMount

        used_luns = [i['block_device__lun'] for i in ManagedTargetMount.objects.all().values('block_device__lun')]
        return LunNode.objects.filter(
                ~Q(lun__in = used_luns),
                host = self)

    def role(self):
        roles = self._role_strings()
        if len(roles) == 0:
            return "Unused"
        else:
            return "/".join(roles)

    def status_string(self, targetmount_statuses = None):
        if targetmount_statuses == None:
            targetmount_statuses = dict([(tm, tm.status_string()) for tm in self.managedtargetmount_set.all()])

        tm_states = set(targetmount_statuses.values())

        from monitor.models import AlertState, HostContactAlert, LNetOfflineAlert
        alerts = AlertState.filter_by_item(self)
        alert_klasses = [a.__class__ for a in alerts]
        if HostContactAlert in alert_klasses:
            return "OFFLINE"
        elif LNetOfflineAlert in alert_klasses or not (set(["STARTED", "SPARE"]) >= tm_states):
            return "WARNING"
        else:
            return "OK"

    def ssh_params(self):
        if self.address.find("@") != -1:
            user,host = self.address.split("@")
        else:
            user = self.DEFAULT_USERNAME
            host = self.address

        if host.find(":") != -1:
            host, port = host.split(":")
        else:
            port = None

        return user, host, port

class Lun(models.Model):
    storage_resource = models.ForeignKey('StorageResourceRecord', blank = True, null = True)

    # Size may be null for LunNodes created when setting up 
    # from a JSON file which just tells us a path.
    size = models.BigIntegerField(blank = True, null = True)

    # Whether the originating StorageResource can be shared between hosts
    # Note: this is ultimately a hint, as it's always possible for a virtual
    # environment to trick us by showing the same IDE device to two hosts, or
    # for shared storage to not provide a serial number.
    shareable = models.BooleanField()

    class Meta:
        unique_together = ('storage_resource',)
        app_label = 'configure'

    @classmethod
    def get_unused_luns(cls):
        """Get all Luns which are not used by Targets"""
        from django.db.models import Q
        from configure.models import ManagedTargetMount
        used_lun_ids = [i['block_device__lun'] for i in ManagedTargetMount.objects.all().values('block_device__lun')]
        return Lun.objects.filter(~Q(pk__in = used_lun_ids))

    @classmethod
    def get_usable_luns(cls):
        """Get all Luns which are not used by Targets and have enough LunNode configuration
        to be used as a Target (i.e. have only one node or at least have a primary node set)"""
        from django.db.models import Count

        # Our result will be a subset of unused_luns
        unused_luns = cls.get_unused_luns()

        # Map of which luns have a primary to avoid doing a query per-lun
        primary_lns = LunNode.objects.filter(primary = True).values('lun')
        luns_with_primary = set()
        for ln in primary_lns:
            luns_with_primary.add(ln['lun'])

        # TODO: avoid O(N) queries
        for lun in unused_luns:
            lunnode_count = lun.lunnode_set.count()
            if lunnode_count == 0:
                # A lun is unusable if it has no LunNodes
                continue
            elif lunnode_count > 1 and not lun.pk in luns_with_primary:
                # A lun is unusable if it has more than one LunNode, and none is identified as primary
                continue
            else:
                yield lun

    def human_kind(self):
        if not self.storage_resource_id:
            return "Unknown"

        from configure.models import StorageResourceRecord
        record = StorageResourceRecord.objects.get(pk = self.storage_resource_id)
        resource_klass = record.to_resource_class()
        return resource_klass.human_class()

    def human_name(self):
        if not self.storage_resource_id:
            lunnode = self.lunnode_set.all()[0]
            return "%s:%s" % (lunnode.host, lunnode.path)

        # TODO: this is a link to the local e.g. ScsiDevice resource: to get the
        # best possible name, we should follow back to VirtualDisk ancestors, and
        # if there is only one VirtualDisk in the ancestry then use its name
        from configure.models import StorageResourceRecord
        record = StorageResourceRecord.objects.get(pk = self.storage_resource_id)
        resource = record.to_resource()
        if record.alias:
            return record.alias
        else:
            return resource.human_string()


    def ha_status(self):
        """Tell the caller two things:
         * is the Lun configured enough for use as a target?
         * is the configuration (if present) HA?
         by returning one of 'unconfigured', 'configured-ha', 'configured-noha'
        """

        HA_CAP_YES = 0
        HA_CAP_NO = 1
        HA_CAP_MAYBE = 2
        CONFIGURED_NO = 3
        CONFIGURED_YES_HA = 4
        CONFIGURED_YES_NOHA = 5

        detail_status = None
        if not self.shareable:
            detail_status = (HA_CAP_NO, CONFIGURED_YES_NOHA)
            return 'configured-noha'
        else:
            lunnode_count = self.lunnode_set.count()
            primary_count = self.lunnode_set.filter(primary = True).count()
            failover_count = self.lunnode_set.filter(primary = False, use = True).count()
            if lunnode_count == 1 and primary_count == 0:
                detail_status = (HA_CAP_MAYBE, CONFIGURED_NO)
                return 'configured-noha'
            elif lunnode_count == 1 and primary_count > 0:
                detail_status = (HA_CAP_MAYBE, CONFIGURED_YES_NOHA)
                return 'configured-noha'
            elif primary_count > 0 and failover_count == 0:
                detail_status = (HA_CAP_YES, CONFIGURED_YES_NOHA)
                return 'configured-noha'
            elif primary_count > 0 and failover_count > 0:
                detail_status = (HA_CAP_YES, CONFIGURED_YES_HA)
                return 'configured-ha'
            else:
                # Has no LunNodes, or has >1 but no primary
                detail_status = (HA_CAP_YES, CONFIGURED_NO)
                return 'unconfigured'

class LunNode(models.Model):
    lun = models.ForeignKey(Lun)
    host = models.ForeignKey(ManagedHost)
    path = models.CharField(max_length = 512)

    storage_resource = models.ForeignKey('StorageResourceRecord', blank = True, null = True)

    # Whether this LunNode should be used as the primary mount point
    # for targets created on this Lun
    primary = models.BooleanField(default = False)
    # Whether this LunNode should be used at all for targets created
    # on this Lun
    use = models.BooleanField(default = True)

    class Meta:
        unique_together = ('host', 'path')
        app_label = 'configure'

    def __str__(self):
        return "%s:%s" % (self.host, self.path)

    def pretty_string(self):
        from monitor.lib.util import sizeof_fmt
        lun_name = self.lun.human_name()
        if lun_name:
            short_name = lun_name
        elif self.path.startswith('/dev/disk/by-path/'):
            short_name = self.path.replace('/dev/disk/by-path/', '', 1)

            # e.g. ip-192.168.122.1:3260-iscsi-iqn.2011-08.com.whamcloud.lab.hydra-1.sdb-lun-0
            if short_name.startswith("ip-") and short_name.find("-iscsi-") != -1:
                iscsi_iqn = "".join(short_name.split("-iscsi-")[1:])
                short_name = "iSCSI %s" % iscsi_iqn

            # e.g. /dev/disk/by-path/pci-0000:00:06.0-scsi-0:0:3:0    
            if short_name.startswith("pci-") and short_name.find("-scsi-") != -1:
                scsi_id = "".join(short_name.split("-scsi-")[1:])
                short_name = "SCSI %s" % scsi_id

            # e.g. /dev/disk/by-path/pci-0000:0a:00.0-fc-0x21000001ff040a42:0x0006000000000000
            if short_name.startswith("pci-") and short_name.find("-fc-") != -1:
                fc_id = "".join(short_name.split("-fc-")[1:])
                short_name = "FC %s" % fc_id

        elif self.path.startswith('/dev/mapper/'):
            # e.g. /dev/mapper/VolGroup00-blob0
            short_name = self.path.replace('/dev/mapper/', '', 1)
            short_name = "DM %s" % short_name
        elif self.path.startswith('/dev/'):
            # e.g. /dev/sda
            short_name = self.path.replace('/dev/', '', 1)
        else:
            short_name = self.path

        size = self.lun.size
        if size:
            human_size = sizeof_fmt(size)
        else:
            human_size = "[size unknown]"

        return "%s (%s)" % (short_name, human_size)

class Monitor(models.Model):
    __metaclass__ = DowncastMetaclass

    host = models.OneToOneField(ManagedHost)

    class Meta:
        app_label = 'configure'

    #idle, tasking, tasked, started, 
    state = models.CharField(max_length = 32, default = 'idle')
    task_id = models.CharField(max_length=36, blank = True, null = True, default = None)
    counter = models.IntegerField(default = 0)
    last_success = models.DateTimeField(blank = True, null = True)

    from django.db import transaction
    @transaction.commit_on_success
    def update(self, **kwargs):
        for k,v in kwargs.items():
            setattr(self, k, v)
        self.save()

    def try_schedule(self):
        """Return True if a run was scheduled, else False"""
        from monitor.tasks import monitor_exec
        from monitor.lib.lustre_audit import audit_log

        if self.state == 'tasking':
            audit_log.warn("Monitor %d found in state 'tasking' (crash recovery).  Going to idle." % self.id)
            self.update(state = 'idle')

        if self.state == 'idle':
            self.update(state = 'tasking', counter = self.counter + 1)
            celery_task = monitor_exec.delay(self.id, self.counter)
            self.update(state = 'tasked', task_id = celery_task.task_id)

            return True
        else:
            return False

    def invoke(self, command, timeout = None):
        """Safe to call on an SshMonitor which has a host assigned, neither
        need to have been saved"""
        from monitor.lib.lustre_audit import audit_log
        from configure.lib.agent import Agent
        try:
            return Agent(self.host, log = audit_log, timeout = timeout).invoke(command)
        except Exception, e:
            return e

class LNetConfiguration(StatefulObject):
    states = ['nids_unknown', 'nids_known']
    initial_state = 'nids_unknown'

    host = models.OneToOneField('ManagedHost')

    def get_nids(self):
        assert(self.state == 'nids_known')
        return [n.nid_string for n in self.nid_set.all()]

    def __str__(self):
        return "%s LNet configuration" % (self.host)

    class Meta:
        app_label = 'configure'

class Nid(models.Model):
    """Simplified NID representation for those we detect already-configured"""
    lnet_configuration = models.ForeignKey(LNetConfiguration)
    nid_string = models.CharField(max_length=128)

    class Meta:
        app_label = 'configure'

class LearnNidsStep(Step):
    def is_idempotent(self):
        return True

    def run(self, kwargs):
        from configure.models import ManagedHost, Nid
        from monitor.lib.lustre_audit import normalize_nid
        host = ManagedHost.objects.get(pk = kwargs['host_id'])
        result = self.invoke_agent(host, "lnet-scan")
        for nid_string in result:
            Nid.objects.get_or_create(
                    lnet_configuration = host.lnetconfiguration,
                    nid_string = normalize_nid(nid_string))

class ConfigureLNetJob(Job, StateChangeJob):
    state_transition = (LNetConfiguration, 'nids_unknown', 'nids_known')
    stateful_object = 'lnet_configuration'
    lnet_configuration = models.ForeignKey(LNetConfiguration)
    state_verb = 'Configure LNet'

    def description(self):
        return "Configuring LNet on %s" % self.lnet_configuration.host

    def get_steps(self):
        return [(LearnNidsStep, {'host_id': self.lnet_configuration.host.id})]

    def get_deps(self):
        return DependOn(self.lnet_configuration.host, "lnet_up")

    class Meta:
        app_label = 'configure'

class ConfigureRsyslogStep(Step):
    def is_idempotent(self):
        return True

    def run(self, kwargs):
        from configure.models import ManagedHost
        from os import uname
        host = ManagedHost.objects.get(id = kwargs['host_id'])
        self.invoke_agent(host, "configure-rsyslog --node %s" % uname()[1])

class UnconfigureRsyslogStep(Step):
    def is_idempotent(self):
        return True

    def run(self, kwargs):
        from configure.models import ManagedHost
        from os import uname
        host = ManagedHost.objects.get(id = kwargs['host_id'])
        self.invoke_agent(host, "unconfigure-rsyslog")

class LearnHostnameStep(Step):
    def is_idempotent(self):
        return True

    def run(self, kwargs):
        from configure.models import ManagedHost
        host = ManagedHost.objects.get(id = kwargs['host_id'])
        fqdn = self.invoke_agent(host, "get-fqdn")

        from django.db import IntegrityError
        try:
            host.fqdn = fqdn
            host.save()
        except IntegrityError:
            from configure.lib.job import job_log
            # TODO: make this an Event or Alert?
            host.fqdn = None
            job_log.error("Cannot complete setup of host %s, it is reporting an already-used FQDN %s" % (host, fqdn))



class SetupHostJob(Job, StateChangeJob):
    state_transition = (ManagedHost, 'unconfigured', 'lnet_unloaded')
    stateful_object = 'managed_host'
    managed_host = models.ForeignKey(ManagedHost)
    state_verb = 'Set up server'

    def description(self):
        return "Setting up server %s" % self.managed_host

    def get_steps(self):
        return [(LearnHostnameStep, {'host_id': self.managed_host.pk}),
                (ConfigureRsyslogStep, {'host_id': self.managed_host.pk})]

    class Meta:
        app_label = 'configure'


class DetectTargetsStep(Step):
    def is_dempotent(self):
        return True

    def run(self, kwargs):
        from configure.models import ManagedHost
        from monitor.lib.lustre_audit import DetectScan

        host_data = {}
        for host in ManagedHost.objects.all():
            data = host.monitor.downcast().invoke('detect-scan')
            host_data[host] = data

        # Stage one: detect MGSs
        for host in ManagedHost.objects.all():
            success = DetectScan().run(host.pk, host_data[host], host_data)
            if not success:
                raise RuntimeError("Audit host %s failed during MGS detection, aborting" % host)

        # Stage two: detect filesystem targets
        for host in ManagedHost.objects.all():
            success = DetectScan().run(host.pk, host_data[host], host_data)
            if not success:
                raise RuntimeError("Audit host %s failed during FS target detection, aborting" % host)

class DetectTargetsJob(Job):
    class Meta:
        app_label = 'configure'

    def description(self):
        return "Scanning for Lustre targets"

    def get_steps(self):
        return [(DetectTargetsStep, {})]

    def get_deps(self):
        from configure.models import ManagedHost
        deps = []
        for host in ManagedHost.objects.all():
            deps.append(DependOn(host.lnetconfiguration, 'nids_known'))

        return DependAll(deps)


class LoadLNetJob(Job, StateChangeJob):
    state_transition = (ManagedHost, 'lnet_unloaded', 'lnet_down')
    stateful_object = 'host'
    host = models.ForeignKey(ManagedHost)
    state_verb = 'Load LNet'

    class Meta:
        app_label = 'configure'

    def description(self):
        return "Loading LNet module on %s" % self.host

    def get_steps(self):
        from configure.lib.job import LoadLNetStep
        return [(LoadLNetStep, {'host_id': self.host.id})]

class UnloadLNetJob(Job, StateChangeJob):
    state_transition = (ManagedHost, 'lnet_down', 'lnet_unloaded')
    stateful_object = 'host'
    host = models.ForeignKey(ManagedHost)
    state_verb = 'Unload LNet'

    class Meta:
        app_label = 'configure'

    def description(self):
        return "Unloading LNet module on %s" % self.host

    def get_steps(self):
        from configure.lib.job import UnloadLNetStep
        return [(UnloadLNetStep, {'host_id': self.host.id})]
    
class StartLNetJob(Job, StateChangeJob):
    state_transition = (ManagedHost, 'lnet_down', 'lnet_up')
    stateful_object = 'host'
    host = models.ForeignKey(ManagedHost)
    state_verb = 'Start LNet'

    class Meta:
        app_label = 'configure'

    def description(self):
        return "Start LNet on %s" % self.host

    def get_steps(self):
        from configure.lib.job import StartLNetStep
        return [(StartLNetStep, {'host_id': self.host.id})]

class StopLNetJob(Job, StateChangeJob):
    state_transition = (ManagedHost, 'lnet_up', 'lnet_down')
    stateful_object = 'host'
    host = models.ForeignKey(ManagedHost)
    state_verb = 'Stop LNet'

    class Meta:
        app_label = 'configure'

    def description(self):
        return "Stop LNet on %s" % self.host

    def get_steps(self):
        from configure.lib.job import StopLNetStep
        return [(StopLNetStep, {'host_id': self.host.id})]

class RemoveHostJob(Job, StateChangeJob):
    state_transition = (ManagedHost, 'lnet_unloaded', 'removed')
    stateful_object = 'host'
    host = models.ForeignKey(ManagedHost)
    state_verb = 'Remove'

    class Meta:
        app_label = 'configure'

    def description(self):
        return "Remove host %s from configuration" % self.host

    def get_steps(self):
        from configure.lib.job import DeleteHostStep
        return [(DeleteHostStep, {'host_id': self.host.id})]

