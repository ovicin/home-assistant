"""
homeassistant
~~~~~~~~~~~~~

Home Assistant is a Home Automation framework for observing the state
of entities and react to changes.
"""

import os
import time
import logging
import threading
import enum
import re
import datetime as dt
import functools as ft

from homeassistant.const import (
    EVENT_HOMEASSISTANT_START, EVENT_HOMEASSISTANT_STOP,
    SERVICE_HOMEASSISTANT_STOP, EVENT_TIME_CHANGED, EVENT_STATE_CHANGED,
    EVENT_CALL_SERVICE, ATTR_NOW, ATTR_DOMAIN, ATTR_SERVICE, MATCH_ALL,
    EVENT_SERVICE_EXECUTED, ATTR_SERVICE_CALL_ID, EVENT_SERVICE_REGISTERED)
import homeassistant.util as util

DOMAIN = "homeassistant"

# How often time_changed event should fire
TIMER_INTERVAL = 1  # seconds

# How long we wait for the result of a service call
SERVICE_CALL_LIMIT = 10  # seconds

# Define number of MINIMUM worker threads.
# During bootstrap of HA (see bootstrap.from_config_dict()) worker threads
# will be added for each component that polls devices.
MIN_WORKER_THREAD = 2

# Pattern for validating entity IDs (format: <domain>.<entity>)
ENTITY_ID_PATTERN = re.compile(r"^(?P<domain>\w+)\.(?P<entity>\w+)$")

_LOGGER = logging.getLogger(__name__)


class HomeAssistant(object):
    """ Core class to route all communication to right components. """

    def __init__(self):
        self.pool = pool = create_worker_pool()
        self.bus = EventBus(pool)
        self.services = ServiceRegistry(self.bus, pool)
        self.states = StateMachine(self.bus)

        # List of loaded components
        self.components = []

        # Remote.API object pointing at local API
        self.local_api = None

        # Directory that holds the configuration
        self.config_dir = os.path.join(os.getcwd(), 'config')

    def get_config_path(self, path):
        """ Returns path to the file within the config dir. """
        return os.path.join(self.config_dir, path)

    def start(self):
        """ Start home assistant. """
        _LOGGER.info(
            "Starting Home Assistant (%d threads)", self.pool.worker_count)

        Timer(self)

        self.bus.fire(EVENT_HOMEASSISTANT_START)

    def block_till_stopped(self):
        """ Will register service homeassistant/stop and
            will block until called. """
        request_shutdown = threading.Event()

        self.services.register(DOMAIN, SERVICE_HOMEASSISTANT_STOP,
                               lambda service: request_shutdown.set())

        while not request_shutdown.isSet():
            try:
                time.sleep(1)

            except KeyboardInterrupt:
                break

        self.stop()

    def track_point_in_time(self, action, point_in_time):
        """
        Adds a listener that fires once at or after a spefic point in time.
        """

        @ft.wraps(action)
        def point_in_time_listener(event):
            """ Listens for matching time_changed events. """
            now = event.data[ATTR_NOW]

            if now >= point_in_time and \
               not hasattr(point_in_time_listener, 'run'):

                # Set variable so that we will never run twice.
                # Because the event bus might have to wait till a thread comes
                # available to execute this listener it might occur that the
                # listener gets lined up twice to be executed. This will make
                # sure the second time it does nothing.
                point_in_time_listener.run = True

                self.bus.remove_listener(EVENT_TIME_CHANGED,
                                         point_in_time_listener)

                action(now)

        self.bus.listen(EVENT_TIME_CHANGED, point_in_time_listener)

    # pylint: disable=too-many-arguments
    def track_time_change(self, action,
                          year=None, month=None, day=None,
                          hour=None, minute=None, second=None):
        """ Adds a listener that will fire if time matches a pattern. """

        # We do not have to wrap the function with time pattern matching logic
        # if no pattern given
        if any((val is not None for val in
                (year, month, day, hour, minute, second))):

            pmp = _process_match_param
            year, month, day = pmp(year), pmp(month), pmp(day)
            hour, minute, second = pmp(hour), pmp(minute), pmp(second)

            @ft.wraps(action)
            def time_listener(event):
                """ Listens for matching time_changed events. """
                now = event.data[ATTR_NOW]

                mat = _matcher

                if mat(now.year, year) and \
                   mat(now.month, month) and \
                   mat(now.day, day) and \
                   mat(now.hour, hour) and \
                   mat(now.minute, minute) and \
                   mat(now.second, second):

                    action(now)

        else:
            @ft.wraps(action)
            def time_listener(event):
                """ Fires every time event that comes in. """
                action(event.data[ATTR_NOW])

        self.bus.listen(EVENT_TIME_CHANGED, time_listener)

    def stop(self):
        """ Stops Home Assistant and shuts down all threads. """
        _LOGGER.info("Stopping")

        self.bus.fire(EVENT_HOMEASSISTANT_STOP)

        # Wait till all responses to homeassistant_stop are done
        self.pool.block_till_done()

        self.pool.stop()

    def get_entity_ids(self, domain_filter=None):
        """
        Returns known entity ids.

        THIS METHOD IS DEPRECATED. Use hass.states.entity_ids
        """
        _LOGGER.warning(
            "hass.get_entiy_ids is deprecated. Use hass.states.entity_ids")

        return self.states.entity_ids(domain_filter)

    def listen_once_event(self, event_type, listener):
        """ Listen once for event of a specific type.

        To listen to all events specify the constant ``MATCH_ALL``
        as event_type.

        Note: at the moment it is impossible to remove a one time listener.

        THIS METHOD IS DEPRECATED. Please use hass.events.listen_once.
        """
        _LOGGER.warning(
            "hass.listen_once_event is deprecated. Use hass.bus.listen_once")

        self.bus.listen_once(event_type, listener)

    def track_state_change(self, entity_ids, action,
                           from_state=None, to_state=None):
        """
        Track specific state changes.
        entity_ids, from_state and to_state can be string or list.
        Use list to match multiple.

        THIS METHOD IS DEPRECATED. Use hass.states.track_change
        """
        _LOGGER.warning((
            "hass.track_state_change is deprecated. "
            "Use hass.states.track_change"))

        self.states.track_change(entity_ids, action, from_state, to_state)

    def call_service(self, domain, service, service_data=None):
        """
        Fires event to call specified service.

        THIS METHOD IS DEPRECATED. Use hass.services.call
        """
        _LOGGER.warning((
            "hass.services.call is deprecated. "
            "Use hass.services.call"))

        self.services.call(domain, service, service_data)


def _process_match_param(parameter):
    """ Wraps parameter in a list if it is not one and returns it. """
    if parameter is None or parameter == MATCH_ALL:
        return MATCH_ALL
    elif isinstance(parameter, str) or not hasattr(parameter, '__iter__'):
        return (parameter,)
    else:
        return tuple(parameter)


def _matcher(subject, pattern):
    """ Returns True if subject matches the pattern.

    Pattern is either a list of allowed subjects or a `MATCH_ALL`.
    """
    return MATCH_ALL == pattern or subject in pattern


class JobPriority(util.OrderedEnum):
    """ Provides priorities for bus events. """
    # pylint: disable=no-init,too-few-public-methods

    EVENT_CALLBACK = 0
    EVENT_SERVICE = 1
    EVENT_STATE = 2
    EVENT_TIME = 3
    EVENT_DEFAULT = 4

    @staticmethod
    def from_event_type(event_type):
        """ Returns a priority based on event type. """
        if event_type == EVENT_TIME_CHANGED:
            return JobPriority.EVENT_TIME
        elif event_type == EVENT_STATE_CHANGED:
            return JobPriority.EVENT_STATE
        elif event_type == EVENT_CALL_SERVICE:
            return JobPriority.EVENT_SERVICE
        elif event_type == EVENT_SERVICE_EXECUTED:
            return JobPriority.EVENT_CALLBACK
        else:
            return JobPriority.EVENT_DEFAULT


def create_worker_pool():
    """ Creates a worker pool to be used. """

    def job_handler(job):
        """ Called whenever a job is available to do. """
        try:
            func, arg = job
            func(arg)
        except Exception:  # pylint: disable=broad-except
            # Catch any exception our service/event_listener might throw
            # We do not want to crash our ThreadPool
            _LOGGER.exception("BusHandler:Exception doing job")

    def busy_callback(worker_count, current_jobs, pending_jobs_count):
        """ Callback to be called when the pool queue gets too big. """

        _LOGGER.warning(
            "WorkerPool:All %d threads are busy and %d jobs pending",
            worker_count, pending_jobs_count)

        for start, job in current_jobs:
            _LOGGER.warning("WorkerPool:Current job from %s: %s",
                            util.datetime_to_str(start), job)

    return util.ThreadPool(job_handler, MIN_WORKER_THREAD, busy_callback)


class EventOrigin(enum.Enum):
    """ Distinguish between origin of event. """
    # pylint: disable=no-init,too-few-public-methods

    local = "LOCAL"
    remote = "REMOTE"

    def __str__(self):
        return self.value


# pylint: disable=too-few-public-methods
class Event(object):
    """ Represents an event within the Bus. """

    __slots__ = ['event_type', 'data', 'origin']

    def __init__(self, event_type, data=None, origin=EventOrigin.local):
        self.event_type = event_type
        self.data = data or {}
        self.origin = origin

    def as_dict(self):
        """ Returns a dict representation of this Event. """
        return {
            'event_type': self.event_type,
            'data': dict(self.data),
            'origin': str(self.origin)
        }

    def __repr__(self):
        # pylint: disable=maybe-no-member
        if self.data:
            return "<Event {}[{}]: {}>".format(
                self.event_type, str(self.origin)[0],
                util.repr_helper(self.data))
        else:
            return "<Event {}[{}]>".format(self.event_type,
                                           str(self.origin)[0])


class EventBus(object):
    """ Class that allows different components to communicate via services
    and events.
    """

    def __init__(self, pool=None):
        self._listeners = {}
        self._lock = threading.Lock()
        self._pool = pool or create_worker_pool()

    @property
    def listeners(self):
        """ Dict with events that is being listened for and the number
        of listeners.
        """
        with self._lock:
            return {key: len(self._listeners[key])
                    for key in self._listeners}

    def fire(self, event_type, event_data=None, origin=EventOrigin.local):
        """ Fire an event. """
        with self._lock:
            # Copy the list of the current listeners because some listeners
            # remove themselves as a listener while being executed which
            # causes the iterator to be confused.
            get = self._listeners.get
            listeners = get(MATCH_ALL, []) + get(event_type, [])

            event = Event(event_type, event_data, origin)

            if event_type != EVENT_TIME_CHANGED:
                _LOGGER.info("Bus:Handling %s", event)

            if not listeners:
                return

            job_priority = JobPriority.from_event_type(event_type)

            for func in listeners:
                self._pool.add_job(job_priority, (func, event))

    def listen(self, event_type, listener):
        """ Listen for all events or events of a specific type.

        To listen to all events specify the constant ``MATCH_ALL``
        as event_type.
        """
        with self._lock:
            if event_type in self._listeners:
                self._listeners[event_type].append(listener)
            else:
                self._listeners[event_type] = [listener]

    def listen_once(self, event_type, listener):
        """ Listen once for event of a specific type.

        To listen to all events specify the constant ``MATCH_ALL``
        as event_type.

        Note: at the moment it is impossible to remove a one time listener.
        """
        @ft.wraps(listener)
        def onetime_listener(event):
            """ Removes listener from eventbus and then fires listener. """
            if not hasattr(onetime_listener, 'run'):
                # Set variable so that we will never run twice.
                # Because the event bus might have to wait till a thread comes
                # available to execute this listener it might occur that the
                # listener gets lined up twice to be executed.
                # This will make sure the second time it does nothing.
                onetime_listener.run = True

                self.remove_listener(event_type, onetime_listener)

                listener(event)

        self.listen(event_type, onetime_listener)

    def remove_listener(self, event_type, listener):
        """ Removes a listener of a specific event_type. """
        with self._lock:
            try:
                self._listeners[event_type].remove(listener)

                # delete event_type list if empty
                if not self._listeners[event_type]:
                    self._listeners.pop(event_type)

            except (KeyError, ValueError):
                # KeyError is key event_type listener did not exist
                # ValueError if listener did not exist within event_type
                pass


class State(object):
    """
    Object to represent a state within the state machine.

    entity_id: the entity that is represented.
    state: the state of the entity
    attributes: extra information on entity and state
    last_changed: last time the state was changed, not the attributes.
    last_updated: last time this object was updated.
    """

    __slots__ = ['entity_id', 'state', 'attributes',
                 'last_changed', 'last_updated']

    def __init__(self, entity_id, state, attributes=None, last_changed=None):
        if not ENTITY_ID_PATTERN.match(entity_id):
            raise InvalidEntityFormatError((
                "Invalid entity id encountered: {}. "
                "Format should be <domain>.<object_id>").format(entity_id))

        self.entity_id = entity_id.lower()
        self.state = state
        self.attributes = attributes or {}
        self.last_updated = dt.datetime.now()

        # Strip microsecond from last_changed else we cannot guarantee
        # state == State.from_dict(state.as_dict())
        # This behavior occurs because to_dict uses datetime_to_str
        # which does not preserve microseconds
        self.last_changed = util.strip_microseconds(
            last_changed or self.last_updated)

    def copy(self):
        """ Creates a copy of itself. """
        return State(self.entity_id, self.state,
                     dict(self.attributes), self.last_changed)

    def as_dict(self):
        """ Converts State to a dict to be used within JSON.
        Ensures: state == State.from_dict(state.as_dict()) """

        return {'entity_id': self.entity_id,
                'state': self.state,
                'attributes': self.attributes,
                'last_changed': util.datetime_to_str(self.last_changed)}

    @classmethod
    def from_dict(cls, json_dict):
        """ Static method to create a state from a dict.
        Ensures: state == State.from_json_dict(state.to_json_dict()) """

        if not (json_dict and
                'entity_id' in json_dict and
                'state' in json_dict):
            return None

        last_changed = json_dict.get('last_changed')

        if last_changed:
            last_changed = util.str_to_datetime(last_changed)

        return cls(json_dict['entity_id'], json_dict['state'],
                   json_dict.get('attributes'), last_changed)

    def __eq__(self, other):
        return (self.__class__ == other.__class__ and
                self.entity_id == other.entity_id and
                self.state == other.state and
                self.attributes == other.attributes)

    def __repr__(self):
        attr = "; {}".format(util.repr_helper(self.attributes)) \
               if self.attributes else ""

        return "<state {}={}{} @ {}>".format(
            self.entity_id, self.state, attr,
            util.datetime_to_str(self.last_changed))


class StateMachine(object):
    """ Helper class that tracks the state of different entities. """

    def __init__(self, bus):
        self._states = {}
        self._bus = bus
        self._lock = threading.Lock()

    def entity_ids(self, domain_filter=None):
        """ List of entity ids that are being tracked. """
        if domain_filter is not None:
            domain_filter = domain_filter.lower()

            return [state.entity_id for key, state
                    in self._states.items()
                    if util.split_entity_id(key)[0] == domain_filter]
        else:
            return list(self._states.keys())

    def all(self):
        """ Returns a list of all states. """
        return [state.copy() for state in self._states.values()]

    def get(self, entity_id):
        """ Returns the state of the specified entity. """
        state = self._states.get(entity_id.lower())

        # Make a copy so people won't mutate the state
        return state.copy() if state else None

    def get_since(self, point_in_time):
        """
        Returns all states that have been changed since point_in_time.
        """
        point_in_time = util.strip_microseconds(point_in_time)

        with self._lock:
            return [state for state in self._states.values()
                    if state.last_updated >= point_in_time]

    def is_state(self, entity_id, state):
        """ Returns True if entity exists and is specified state. """
        entity_id = entity_id.lower()

        return (entity_id in self._states and
                self._states[entity_id].state == state)

    def remove(self, entity_id):
        """ Removes an entity from the state machine.

        Returns boolean to indicate if an entity was removed. """
        entity_id = entity_id.lower()

        with self._lock:
            return self._states.pop(entity_id, None) is not None

    def set(self, entity_id, new_state, attributes=None):
        """ Set the state of an entity, add entity if it does not exist.

        Attributes is an optional dict to specify attributes of this state.

        If you just update the attributes and not the state, last changed will
        not be affected.
        """
        entity_id = entity_id.lower()
        new_state = str(new_state)
        attributes = attributes or {}

        with self._lock:
            old_state = self._states.get(entity_id)

            is_existing = old_state is not None
            same_state = is_existing and old_state.state == new_state
            same_attr = is_existing and old_state.attributes == attributes

            # If state did not exist or is different, set it
            if not (same_state and same_attr):
                last_changed = old_state.last_changed if same_state else None

                state = State(entity_id, new_state, attributes, last_changed)
                self._states[entity_id] = state

                event_data = {'entity_id': entity_id, 'new_state': state}

                if old_state:
                    event_data['old_state'] = old_state

                self._bus.fire(EVENT_STATE_CHANGED, event_data)

    def track_change(self, entity_ids, action, from_state=None, to_state=None):
        """
        Track specific state changes.
        entity_ids, from_state and to_state can be string or list.
        Use list to match multiple.

        Returns the listener that listens on the bus for EVENT_STATE_CHANGED.
        Pass the return value into hass.bus.remove_listener to remove it.
        """
        from_state = _process_match_param(from_state)
        to_state = _process_match_param(to_state)

        # Ensure it is a lowercase list with entity ids we want to match on
        if isinstance(entity_ids, str):
            entity_ids = (entity_ids.lower(),)
        else:
            entity_ids = tuple(entity_id.lower() for entity_id in entity_ids)

        @ft.wraps(action)
        def state_listener(event):
            """ The listener that listens for specific state changes. """
            if event.data['entity_id'] not in entity_ids:
                return

            if 'old_state' in event.data:
                old_state = event.data['old_state'].state
            else:
                old_state = None

            if _matcher(old_state, from_state) and \
               _matcher(event.data['new_state'].state, to_state):

                action(event.data['entity_id'],
                       event.data.get('old_state'),
                       event.data['new_state'])

        self._bus.listen(EVENT_STATE_CHANGED, state_listener)

        return state_listener


# pylint: disable=too-few-public-methods
class ServiceCall(object):
    """ Represents a call to a service. """

    __slots__ = ['domain', 'service', 'data']

    def __init__(self, domain, service, data=None):
        self.domain = domain
        self.service = service
        self.data = data or {}

    def __repr__(self):
        if self.data:
            return "<ServiceCall {}.{}: {}>".format(
                self.domain, self.service, util.repr_helper(self.data))
        else:
            return "<ServiceCall {}.{}>".format(self.domain, self.service)


class ServiceRegistry(object):
    """ Offers services over the eventbus. """

    def __init__(self, bus, pool=None):
        self._services = {}
        self._lock = threading.Lock()
        self._pool = pool or create_worker_pool()
        self._bus = bus
        self._cur_id = 0
        bus.listen(EVENT_CALL_SERVICE, self._event_to_service_call)

    @property
    def services(self):
        """ Dict with per domain a list of available services. """
        with self._lock:
            return {domain: list(self._services[domain].keys())
                    for domain in self._services}

    def has_service(self, domain, service):
        """ Returns True if specified service exists. """
        return service in self._services.get(domain, [])

    def register(self, domain, service, service_func):
        """ Register a service. """
        with self._lock:
            if domain in self._services:
                self._services[domain][service] = service_func
            else:
                self._services[domain] = {service: service_func}

            self._bus.fire(
                EVENT_SERVICE_REGISTERED,
                {ATTR_DOMAIN: domain, ATTR_SERVICE: service})

    def call(self, domain, service, service_data=None, blocking=False):
        """
        Calls specified service.
        Specify blocking=True to wait till service is executed.
        Waits a maximum of SERVICE_CALL_LIMIT.

        If blocking = True, will return boolean if service executed
        succesfully within SERVICE_CALL_LIMIT.

        This method will fire an event to call the service.
        This event will be picked up by this ServiceRegistry and any
        other ServiceRegistry that is listening on the EventBus.

        Because the service is sent as an event you are not allowed to use
        the keys ATTR_DOMAIN and ATTR_SERVICE in your service_data.
        """
        call_id = self._generate_unique_id()
        event_data = service_data or {}
        event_data[ATTR_DOMAIN] = domain
        event_data[ATTR_SERVICE] = service
        event_data[ATTR_SERVICE_CALL_ID] = call_id

        if blocking:
            executed_event = threading.Event()

            def service_executed(call):
                """
                Called when a service is executed.
                Will set the event if matches our service call.
                """
                if call.data[ATTR_SERVICE_CALL_ID] == call_id:
                    executed_event.set()

                    self._bus.remove_listener(
                        EVENT_SERVICE_EXECUTED, service_executed)

            self._bus.listen(EVENT_SERVICE_EXECUTED, service_executed)

        self._bus.fire(EVENT_CALL_SERVICE, event_data)

        if blocking:
            # wait will return False if event not set after our limit has
            # passed. If not set, clean up the listener
            if not executed_event.wait(SERVICE_CALL_LIMIT):
                self._bus.remove_listener(
                    EVENT_SERVICE_EXECUTED, service_executed)

                return False

            return True

    def _event_to_service_call(self, event):
        """ Calls a service from an event. """
        service_data = dict(event.data)
        domain = service_data.pop(ATTR_DOMAIN, None)
        service = service_data.pop(ATTR_SERVICE, None)

        with self._lock:
            if domain in self._services and service in self._services[domain]:
                service_call = ServiceCall(domain, service, service_data)

                # Add a job to the pool that calls _execute_service
                self._pool.add_job(JobPriority.EVENT_SERVICE,
                                   (self._execute_service,
                                    (self._services[domain][service],
                                     service_call)))

    def _execute_service(self, service_and_call):
        """ Executes a service and fires a SERVICE_EXECUTED event. """
        service, call = service_and_call

        service(call)

        self._bus.fire(
            EVENT_SERVICE_EXECUTED, {
                ATTR_SERVICE_CALL_ID: call.data[ATTR_SERVICE_CALL_ID]
            })

    def _generate_unique_id(self):
        """ Generates a unique service call id. """
        self._cur_id += 1
        return "{}-{}".format(id(self), self._cur_id)


class Timer(threading.Thread):
    """ Timer will sent out an event every TIMER_INTERVAL seconds. """

    def __init__(self, hass, interval=None):
        threading.Thread.__init__(self)

        self.daemon = True
        self.hass = hass
        self.interval = interval or TIMER_INTERVAL
        self._stop_event = threading.Event()

        # We want to be able to fire every time a minute starts (seconds=0).
        # We want this so other modules can use that to make sure they fire
        # every minute.
        assert 60 % self.interval == 0, "60 % TIMER_INTERVAL should be 0!"

        hass.bus.listen_once(EVENT_HOMEASSISTANT_START,
                             lambda event: self.start())

    def run(self):
        """ Start the timer. """

        self.hass.bus.listen_once(EVENT_HOMEASSISTANT_STOP,
                                  lambda event: self._stop_event.set())

        _LOGGER.info("Timer:starting")

        last_fired_on_second = -1

        calc_now = dt.datetime.now
        interval = self.interval

        while not self._stop_event.isSet():
            now = calc_now()

            # First check checks if we are not on a second matching the
            # timer interval. Second check checks if we did not already fire
            # this interval.
            if now.second % interval or \
               now.second == last_fired_on_second:

                # Sleep till it is the next time that we have to fire an event.
                # Aim for halfway through the second that fits TIMER_INTERVAL.
                # If TIMER_INTERVAL is 10 fire at .5, 10.5, 20.5, etc seconds.
                # This will yield the best results because time.sleep() is not
                # 100% accurate because of non-realtime OS's
                slp_seconds = interval - now.second % interval + \
                    .5 - now.microsecond/1000000.0

                time.sleep(slp_seconds)

                now = calc_now()

            last_fired_on_second = now.second

            self.hass.bus.fire(EVENT_TIME_CHANGED, {ATTR_NOW: now})


class HomeAssistantError(Exception):
    """ General Home Assistant exception occured. """
    pass


class InvalidEntityFormatError(HomeAssistantError):
    """ When an invalid formatted entity is encountered. """
    pass


class NoEntitySpecifiedError(HomeAssistantError):
    """ When no entity is specified. """
    pass
