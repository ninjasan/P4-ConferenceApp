#!/usr/bin/env python

"""
conference.py -- Udacity conference server-side Python App Engine API;
    uses Google Cloud Endpoints

$Id: conference.py,v 1.25 2014/05/24 23:42:19 wesc Exp wesc $

created by wesc on 2014 apr 21

"""

__author__ = 'wesc+api@google.com (Wesley Chun)'

from datetime import datetime

import endpoints
from protorpc import messages
from protorpc import message_types
from protorpc import remote

from google.appengine.api import memcache
from google.appengine.api import taskqueue
from google.appengine.ext import ndb

from models import ConflictException
from models import Profile
from models import ProfileMiniForm
from models import ProfileForm
from models import StringMessage
from models import BooleanMessage
from models import Conference
from models import ConferenceForm
from models import ConferenceForms
from models import ConferenceQueryForms
from models import TeeShirtSize
from models import Session
from models import SessionForm
from models import SessionForms
from models import TypeOfSession

from settings import WEB_CLIENT_ID
from settings import ANDROID_CLIENT_ID
from settings import IOS_CLIENT_ID
from settings import ANDROID_AUDIENCE

from utils import getUserId, validateTime

EMAIL_SCOPE = endpoints.EMAIL_SCOPE
API_EXPLORER_CLIENT_ID = endpoints.API_EXPLORER_CLIENT_ID
MEMCACHE_ANNOUNCEMENTS_KEY = "RECENT_ANNOUNCEMENTS"
MEMCACHE_FEATURED_SPEAKER_KEY = "FEATURED SPEAKER"
ANNOUNCEMENT_TPL = ('Last chance to attend! The following conferences '
                    'are nearly sold out: %s')
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -

DEFAULTS_CONF = {
    "city": "Default City",
    "maxAttendees": 0,
    "seatsAvailable": 0,
    "topics": ["Default", "Topic"],
}

DEFAULTS_SESSION = {
    "highlights": "Default",
    "duration": 30,
    "speaker": ["Default"],
    "start_time": 0,
}

OPERATORS = {
    'EQ': '=',
    'GT': '>',
    'GTEQ': '>=',
    'LT': '<',
    'LTEQ': '<=',
    'NE': '!='
}

FIELDS = {
    'CITY': 'city',
    'TOPIC': 'topics',
    'MONTH': 'month',
    'MAX_ATTENDEES': 'maxAttendees',
}

CONF_GET_REQUEST = endpoints.ResourceContainer(
        message_types.VoidMessage,
        websafeConferenceKey=messages.StringField(1),
)

CONF_POST_REQUEST = endpoints.ResourceContainer(
        ConferenceForm,
        websafeConferenceKey=messages.StringField(1),
)

SESSION_POST_REQUEST = endpoints.ResourceContainer(
        SessionForm,
        websafeConferenceKey=messages.StringField(1),
)

SESSION_BY_SPEAKER_GET_REQUEST = endpoints.ResourceContainer(
        message_types.VoidMessage,
        speaker=messages.StringField(1),
)

SESSION_BY_TYPE_GET_REQUEST = endpoints.ResourceContainer(
        message_types.VoidMessage,
        websafeConferenceKey=messages.StringField(1),
        typeOfSession=messages.EnumField(TypeOfSession, 2),
)

SESSION_WISHLIST_REQUEST = endpoints.ResourceContainer(
        message_types.VoidMessage,
        websafeSessionKey=messages.StringField(1),
)

SESSION_DURATION_REQUEST = endpoints.ResourceContainer(
        message_types.VoidMessage,
        websafeConferenceKey=messages.StringField(1),
        minDuration=messages.IntegerField(2),
        maxDuration=messages.IntegerField(3),
)


# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -


@endpoints.api(name='conference', version='v1', audiences=[ANDROID_AUDIENCE],
               allowed_client_ids=[WEB_CLIENT_ID,
                                   API_EXPLORER_CLIENT_ID,
                                   ANDROID_CLIENT_ID,
                                   IOS_CLIENT_ID],
               scopes=[EMAIL_SCOPE])
class ConferenceApi(remote.Service):
    """Conference API v0.1"""

    # - - - Conference objects - - - - - - - - - - - - - - - - -

    def _copyConferenceToForm(self, conf, displayName):
        """Copy relevant fields from Conference to ConferenceForm."""
        cf = ConferenceForm()
        for field in cf.all_fields():
            if hasattr(conf, field.name):
                # convert Date to date string; just copy others
                if field.name.endswith('Date'):
                    setattr(cf, field.name, str(getattr(conf, field.name)))
                else:
                    setattr(cf, field.name, getattr(conf, field.name))
            elif field.name == "websafeKey":
                setattr(cf, field.name, conf.key.urlsafe())
        if displayName:
            setattr(cf, 'organizerDisplayName', displayName)
        cf.check_initialized()
        return cf

    def _createConferenceObject(self, request):
        """
            Create or update Conference object, returning
            ConferenceForm/request.
        """
        # preload necessary data items
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')
        user_id = getUserId(user)

        if not request.name:
            raise endpoints.BadRequestException(
                    "Conference 'name' field required"
            )

        # copy ConferenceForm/ProtoRPC Message into dict
        data = {
            field.name: getattr(request, field.name)
                        for field in request.all_fields()
            }
        del data['websafeKey']
        del data['organizerDisplayName']

        # add default values for those missing (both data model &
        # outbound Message)
        for df in DEFAULTS_CONF:
            if data[df] in (None, []):
                data[df] = DEFAULTS_CONF[df]
                setattr(request, df, DEFAULTS_CONF[df])

        # convert dates from strings to Date objects; set month based
        # on start_date
        if data['startDate']:
            data['startDate'] = datetime.strptime(data['startDate'][:10],
                                                  "%Y-%m-%d").date()
            data['month'] = data['startDate'].month
        else:
            data['month'] = 0
        if data['endDate']:
            data['endDate'] = datetime.strptime(data['endDate'][:10],
                                                "%Y-%m-%d").date()

        # set seatsAvailable to be same as maxAttendees on creation
        if data["maxAttendees"] > 0:
            data["seatsAvailable"] = data["maxAttendees"]
        # generate Profile Key based on user ID and Conference
        # ID based on Profile key get Conference key from ID
        p_key = ndb.Key(Profile, user_id)
        c_id = Conference.allocate_ids(size=1, parent=p_key)[0]
        c_key = ndb.Key(Conference, c_id, parent=p_key)
        data['key'] = c_key
        data['organizerUserId'] = request.organizerUserId = user_id

        # create Conference, send email to organizer confirming
        # creation of Conference & return (modified) ConferenceForm
        Conference(**data).put()
        taskqueue.add(params={'email': user.email(),
                              'conferenceInfo': repr(request)},
                      url='/tasks/send_confirmation_email'
                      )
        return request

    @ndb.transactional()
    def _updateConferenceObject(self, request):
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')
        user_id = getUserId(user)

        # copy ConferenceForm/ProtoRPC Message into dict
        data = {field.name: getattr(request, field.name)
                for field in request.all_fields()}

        # update existing conference
        conf = ndb.Key(urlsafe=request.websafeConferenceKey).get()
        # check that conference exists
        if not conf:
            raise endpoints.NotFoundException(
                    'No conference found with key: %s' %
                    request.websafeConferenceKey)

        # check that user is owner
        if user_id != conf.organizerUserId:
            raise endpoints.ForbiddenException(
                    'Only the owner can update the conference.')

        # Not getting all the fields, so don't create a new object; just
        # copy relevant fields from ConferenceForm to Conference object
        for field in request.all_fields():
            data = getattr(request, field.name)
            # only copy fields where we get data
            if data not in (None, []):
                # special handling for dates (convert string to Date)
                if field.name in ('startDate', 'endDate'):
                    data = datetime.strptime(data, "%Y-%m-%d").date()
                    if field.name == 'startDate':
                        conf.month = data.month
                # write to Conference object
                setattr(conf, field.name, data)
        conf.put()
        prof = ndb.Key(Profile, user_id).get()
        return self._copyConferenceToForm(conf, getattr(prof, 'displayName'))

    @endpoints.method(ConferenceForm, ConferenceForm, path='conference',
                      http_method='POST', name='createConference')
    def createConference(self, request):
        """Create new conference."""
        return self._createConferenceObject(request)

    @endpoints.method(CONF_POST_REQUEST, ConferenceForm,
                      path='conference/{websafeConferenceKey}',
                      http_method='PUT', name='updateConference')
    def updateConference(self, request):
        """Update conference w/provided fields & return w/updated info."""
        return self._updateConferenceObject(request)

    @endpoints.method(CONF_GET_REQUEST, ConferenceForm,
                      path='conference/{websafeConferenceKey}',
                      http_method='GET', name='getConference')
    def getConference(self, request):
        """Return requested conference (by websafeConferenceKey)."""
        # get Conference object from request; bail if not found
        conf = ndb.Key(urlsafe=request.websafeConferenceKey).get()
        if not conf:
            raise endpoints.NotFoundException(
                    'No conference found with key: %s' %
                    request.websafeConferenceKey)
        prof = conf.key.parent().get()
        # return ConferenceForm
        return self._copyConferenceToForm(conf, getattr(prof, 'displayName'))

    @endpoints.method(message_types.VoidMessage, ConferenceForms,
                      path='getConferencesCreated',
                      http_method='POST', name='getConferencesCreated')
    def getConferencesCreated(self, request):
        """Return conferences created by user."""
        # make sure user is authed
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')
        user_id = getUserId(user)

        # create ancestor query for all key matches for this user
        confs = Conference.query(ancestor=ndb.Key(Profile, user_id))
        prof = ndb.Key(Profile, user_id).get()
        # return set of ConferenceForm objects per Conference
        return ConferenceForms(
                items=[self._copyConferenceToForm(conf,
                                                  getattr(prof, 'displayName'))
                                                  for conf in confs]
        )

    def _getQuery(self, request):
        """Return formatted query from the submitted filters."""
        q = Conference.query()
        inequality_filter, filters = self._formatFilters(request.filters)

        # If exists, sort on inequality filter first
        if not inequality_filter:
            q = q.order(Conference.name)
        else:
            q = q.order(ndb.GenericProperty(inequality_filter))
            q = q.order(Conference.name)

        for filtr in filters:
            if filtr["field"] in ["month", "maxAttendees"]:
                filtr["value"] = int(filtr["value"])
            formatted_query = ndb.query.FilterNode(filtr["field"],
                                                   filtr["operator"],
                                                   filtr["value"])
            q = q.filter(formatted_query)
        return q

    def _formatFilters(self, filters):
        """Parse, check validity and format user supplied filters."""
        formatted_filters = []
        inequality_field = None

        for f in filters:
            filtr = {field.name: getattr(f, field.name)
                     for field in f.all_fields()}

            try:
                filtr["field"] = FIELDS[filtr["field"]]
                filtr["operator"] = OPERATORS[filtr["operator"]]
            except KeyError:
                raise endpoints.BadRequestException(
                        "Filter contains invalid field or operator."
                )

            # Every operation except "=" is an inequality
            if filtr["operator"] != "=":
                # check if inequality operation has been used
                # in previous filters disallow the filter if inequality was
                # performed on a different field before track the field on
                # which the inequality operation is performed
                if inequality_field and inequality_field != filtr["field"]:
                    raise endpoints.BadRequestException(
                            "Inequality filter is allowed on only one field."
                    )
                else:
                    inequality_field = filtr["field"]

            formatted_filters.append(filtr)
        return (inequality_field, formatted_filters)

    @endpoints.method(ConferenceQueryForms, ConferenceForms,
                      path='queryConferences',
                      http_method='POST',
                      name='queryConferences')
    def queryConferences(self, request):
        """Query for conferences."""
        conferences = self._getQuery(request)

        # need to fetch organiser displayName from profiles
        # get all keys and use get_multi for speed
        organisers = [(ndb.Key(Profile, conf.organizerUserId))
                      for conf in conferences]
        profiles = ndb.get_multi(organisers)

        # put display names in a dict for easier fetching
        names = {}
        for profile in profiles:
            names[profile.key.id()] = profile.displayName

        # return individual ConferenceForm object per Conference
        return ConferenceForms(
                items=[self._copyConferenceToForm(
                        conf,
                        names[conf.organizerUserId])
                        for conf in conferences]
        )

    # - - - Profile objects - - - - - - - - - - - - - - - - - - -

    def _copyProfileToForm(self, prof):
        """Copy relevant fields from Profile to ProfileForm."""
        # copy relevant fields from Profile to ProfileForm
        pf = ProfileForm()
        for field in pf.all_fields():
            if hasattr(prof, field.name):
                # convert t-shirt string to Enum; just copy others
                if field.name == 'teeShirtSize':
                    setattr(pf, field.name, getattr(TeeShirtSize,
                                                    getattr(prof, field.name)))
                else:
                    setattr(pf, field.name, getattr(prof, field.name))
        pf.check_initialized()
        return pf

    def _getProfileFromUser(self):
        """
            Return user Profile from datastore, creating new one if
            non-existent.
        """
        # make sure user is authed
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')

        # get Profile from datastore
        user_id = getUserId(user)
        p_key = ndb.Key(Profile, user_id)
        profile = p_key.get()
        # create new Profile if not there
        if not profile:
            profile = Profile(
                    key=p_key,
                    displayName=user.nickname(),
                    mainEmail=user.email(),
                    teeShirtSize=str(TeeShirtSize.NOT_SPECIFIED),
            )
            profile.put()

        return profile  # return Profile

    def _doProfile(self, save_request=None):
        """Get user Profile and return to user, possibly updating it first."""
        # get user Profile
        prof = self._getProfileFromUser()

        # if saveProfile(), process user-modifyable fields
        if save_request:
            for field in ('displayName', 'teeShirtSize'):
                if hasattr(save_request, field):
                    val = getattr(save_request, field)
                    if val:
                        setattr(prof, field, str(val))
                        # if field == 'teeShirtSize':
                        #    setattr(prof, field, str(val).upper())
                        # else:
                        #    setattr(prof, field, val)
                        prof.put()

        # return ProfileForm
        return self._copyProfileToForm(prof)

    @endpoints.method(message_types.VoidMessage, ProfileForm,
                      path='profile', http_method='GET', name='getProfile')
    def getProfile(self, request):
        """Return user profile."""
        return self._doProfile()

    @endpoints.method(ProfileMiniForm, ProfileForm,
                      path='profile', http_method='POST', name='saveProfile')
    def saveProfile(self, request):
        """Update & return user profile."""
        return self._doProfile(request)

    # - - - Conference Announcements - - - - - - - - - - - - - - - - - - - -

    @staticmethod
    def _cacheAnnouncement():
        """Create Announcement & assign to memcache; used by
        memcache cron job & putAnnouncement().
        """
        confs = Conference.query(ndb.AND(
                Conference.seatsAvailable <= 5,
                Conference.seatsAvailable > 0)
        ).fetch(projection=[Conference.name])

        if confs:
            # If there are almost sold out conferences,
            # format announcement and set it in memcache
            announcement = ANNOUNCEMENT_TPL % (
                ', '.join(conf.name for conf in confs))
            memcache.set(MEMCACHE_ANNOUNCEMENTS_KEY, announcement)
        else:
            # If there are no sold out conferences,
            # delete the memcache announcements entry
            announcement = ""
            memcache.delete(MEMCACHE_ANNOUNCEMENTS_KEY)

        return announcement

    @endpoints.method(message_types.VoidMessage, StringMessage,
                      path='conference/announcement/get',
                      http_method='GET', name='getAnnouncement')
    def getAnnouncement(self, request):
        """Return Announcement from memcache."""
        return StringMessage(
                data=memcache.get(MEMCACHE_ANNOUNCEMENTS_KEY) or
                     ""
               )

    # - - - Session Announcements - - - - - - - - - - - - - - - - - - - -

    @staticmethod
    def _setFeaturedSpeaker(speaker, wsck):
        """
            After creating a new session in a conference, the speaker is
            checked. If there is more than one session by this speaker at this
            conference, a Memcache entry is created/updated with the speaker
            and session names.

        Params:
            - speaker: the speaker that was just added to the conference
            - wsck: the websafeConferenceKey representing a URL safe id for the
                    conference the speaker is speaking at
        Returns: nothing
        """
        conf = ndb.Key(urlsafe=wsck).get()
        sessions = Session.query(ancestor=conf.key)
        sessions_by_speaker = sessions.filter(
                Session.speaker == speaker
        ).fetch(
                projection=[Session.name]
        )

        if len(sessions_by_speaker) > 1:
            text_base = ('Featured Speaker {0} Speaking at '
                         'the following sessions: {1}, at the {2} conference')
            announcement = text_base.format(
                    speaker,
                    ', '.join(session.name for session in sessions_by_speaker),
                    conf.name)
            memcache.set(MEMCACHE_FEATURED_SPEAKER_KEY, announcement)
            # Otherwise, leave the featured speaker as is.

    @endpoints.method(message_types.VoidMessage, StringMessage,
                      path='speaker/featured',
                      http_method='GET', name='getFeaturedSpeaker')
    def getFeaturedSpeaker(self, request):
        """
            Checks memcache for the Featured Speaker Key.

        :param request object, which in this case is void
        :return: a string representing the featured speaker, if there is one
        """
        return StringMessage(
                data=memcache.get(MEMCACHE_FEATURED_SPEAKER_KEY) or ""
        )

    # - - - Registration - - - - - - - - - - - - - - - - - - - -

    @ndb.transactional(xg=True)
    def _conferenceRegistration(self, request, reg=True):
        """Register or unregister user for selected conference."""
        retval = None
        prof = self._getProfileFromUser()  # get user Profile

        # check if conf exists given websafeConfKey
        # get conference; check that it exists
        wsck = request.websafeConferenceKey
        conf = ndb.Key(urlsafe=wsck).get()
        if not conf:
            raise endpoints.NotFoundException(
                    'No conference found with key: %s' % wsck)

        # register
        if reg:
            # check if user already registered otherwise add
            if wsck in prof.conferenceKeysToAttend:
                raise ConflictException(
                        "You have already registered for this conference")

            # check if seats avail
            if conf.seatsAvailable <= 0:
                raise ConflictException(
                        "There are no seats available.")

            # register user, take away one seat
            prof.conferenceKeysToAttend.append(wsck)
            conf.seatsAvailable -= 1
            retval = True

        # unregister
        else:
            # check if user already registered
            if wsck in prof.conferenceKeysToAttend:

                # unregister user, add back one seat
                prof.conferenceKeysToAttend.remove(wsck)
                conf.seatsAvailable += 1
                retval = True
            else:
                retval = False

        # write things back to the datastore & return
        prof.put()
        conf.put()
        return BooleanMessage(data=retval)

    @endpoints.method(message_types.VoidMessage, ConferenceForms,
                      path='conferences/attending',
                      http_method='GET', name='getConferencesToAttend')
    def getConferencesToAttend(self, request):
        """Get list of conferences that user has registered for."""
        prof = self._getProfileFromUser()  # get user Profile
        conf_keys = [ndb.Key(urlsafe=wsck)
                     for wsck in prof.conferenceKeysToAttend]
        conferences = ndb.get_multi(conf_keys)

        # get organizers
        organisers = [ndb.Key(Profile,
                              conf.organizerUserId)for conf in conferences]
        profiles = ndb.get_multi(organisers)

        # put display names in a dict for easier fetching
        names = {}
        for profile in profiles:
            names[profile.key.id()] = profile.displayName

        # return set of ConferenceForm objects per Conference
        return ConferenceForms(
                items=[self._copyConferenceToForm(conf,
                                                  names[conf.organizerUserId])
                                                  for conf in conferences]
        )

    @endpoints.method(CONF_GET_REQUEST, BooleanMessage,
                      path='conference/{websafeConferenceKey}',
                      http_method='POST', name='registerForConference')
    def registerForConference(self, request):
        """Register user for selected conference."""
        return self._conferenceRegistration(request)

    @endpoints.method(CONF_GET_REQUEST, BooleanMessage,
                      path='conference/{websafeConferenceKey}',
                      http_method='DELETE', name='unregisterFromConference')
    def unregisterFromConference(self, request):
        """Unregister user for selected conference."""
        return self._conferenceRegistration(request, reg=False)

    @endpoints.method(message_types.VoidMessage, ConferenceForms,
                      path='filterPlayground',
                      http_method='GET', name='filterPlayground')
    def filterPlayground(self, request):
        """Filter Playground"""
        q = Conference.query()
        # field = "city"
        # operator = "="
        # value = "London"
        # f = ndb.query.FilterNode(field, operator, value)
        # q = q.filter(f)
        q = q.filter(Conference.city == "London")
        q = q.filter(Conference.topics == "Medical Innovations")
        q = q.filter(Conference.month == 6)

        return ConferenceForms(
                items=[self._copyConferenceToForm(conf, "") for conf in q]
        )

    # Sessions  - - - - - - - - - - - - - - - - - - - - - - - - - -

    def _copySessionToForm(self, session):
        """
            Helper function that copies data from the session object to a
            SessionForm for output

        :param session: object presenting the Conference Session to be copied
        :return: SessionForm - an object in the format of the SessionForm model
        """
        """Copy relevant fields from Conference to ConferenceForm."""
        sf = SessionForm()
        for field in sf.all_fields():
            if hasattr(session, field.name):
                # convert Date to date string; just copy others
                if field.name == 'date':
                    setattr(sf, field.name, str(getattr(session, field.name)))
                elif field.name == 'type_of_session':
                    val = (getattr(session, field.name))
                    if val:
                        val = str(val).upper()
                        setattr(sf, field.name, getattr(TypeOfSession, val))
                else:
                    setattr(sf, field.name, getattr(session, field.name))
            elif field.name == "websafeKey":
                setattr(sf, field.name, session.key.urlsafe())
        sf.check_initialized()
        return sf

    def _createSessionObject(self, request):
        """
            Helper function that actual creates the session object

        :param request: containing all the data needed to initialize the
                        session
        :return SessionForm object: representing the session that was just
                                    created
        """

        # Verify the user is authorized
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')
        user_id = getUserId(user)

        # verify conference exists and the user is the conference organizer
        conf = ndb.Key(urlsafe=request.websafeConferenceKey).get()
        conf_id = ndb.Key(urlsafe=request.websafeConferenceKey).id()
        if not conf:
            raise endpoints.NotFoundException(
                    'No conference found with key: %s' %
                    request.websafeConferenceKey)
        if user_id != conf.organizerUserId:
            raise endpoints.ForbiddenException(
                    "You can't make sessions for this conference!"
            )

        # verify required fields are present
        if not request.name:
            raise endpoints.BadRequestException("Session 'name' field required")

        # copy SessionForm/ProtoRPC Message into a dictionary
        data = {field.name: getattr(request, field.name)
                for field in request.all_fields()}
        del data['websafeKey']
        del data['websafeConferenceKey']

        # add default values for those missing (both data model &
        # outbound Message)
        for df in DEFAULTS_SESSION:
            if data[df] in (None, []):
                data[df] = DEFAULTS_SESSION[df]
                setattr(request, df, DEFAULTS_SESSION[df])

        # double check start_time is a valid time
        data['start_time'] = validateTime(data['start_time'])

        # Validate that the type of session is good
        if data['type_of_session']:
            data['type_of_session'] = str(data['type_of_session']).upper()

        # convert dates from strings to Date objects; set month based on
        # start_date
        if data['date']:
            data['date'] = datetime.strptime(data['date'][:10],
                                             "%Y-%m-%d").date()

        # generate Profile Key based on user ID and Conference
        # ID based on Profile key get Conference key from ID
        s_id = Session.allocate_ids(size=1, parent=conf.key)[0]
        s_key = ndb.Key(Session, s_id, parent=conf.key)
        data['key'] = s_key
        data['conference_id'] = request.conference_id = conf_id

        # create Session, add task to see if the featured speaker
        # needs to be updated and then return the Session in a SessionForm
        Session(**data).put()
        taskqueue.add(params={'speaker': data['speaker'],
                              'wsck': request.websafeConferenceKey},
                      url='/tasks/set_featured_speaker'
                      )
        return self._copySessionToForm(request)

    def _sessionWishlist(self, request, do_add=True):
        """
            Helper function that does the actual work to add/remove a session
            to/from a user's wishlist

        :param request: contains the websafeSessionKey (i.e. the id of the
                        session to add to the user's wishlist
        :param do_add: boolean representing if the session should be added
                       or removed from the user's wishlist
        :return: boolean representing if the request work was formed
                 successfully
        """

        # check if the session exists, given websafeKey
        wssk = request.websafeSessionKey
        session = ndb.Key(urlsafe=wssk).get()
        if not session:
            raise endpoints.NotFoundException(
                    'No session found with key: %s' % wssk)

        retval = None
        prof = self._getProfileFromUser()  # get user Profile
        if do_add:  # add to wishlist
            # check if user already registered otherwise add
            if wssk in prof.sessionKeysInWishlist:
                raise ConflictException(
                        "You have already added this session to your wishlist")
            prof.sessionKeysInWishlist.append(wssk)
            retval = True
        else:  # remove from wishlist
            # check if user already registered, and removes the user
            if wssk in prof.sessionKeysInWishlist:
                prof.sessionKeysInWishlist.remove(wssk)
                retval = True
            else:
                retval = False

        # write updates back to the datastore & return
        prof.put()
        return BooleanMessage(data=retval)

    # CONF-specific session queries
    @endpoints.method(SESSION_POST_REQUEST, SessionForm,
                      path='conference/{websafeConferenceKey}/session',
                      http_method='POST', name='createSession')
    def createSession(self, request):
        """
            Public facing endpoint used for a user to create a new
            session in the conference

        :param request object containing
                - SessionForm: a sessionForm object representing the input
                               from the user
                - websafeConferenceKey: the websafeKey of the Conference to
                                        add this session to
        :return: response of the _createSessionObject function
        """
        return self._createSessionObject(request)

    @endpoints.method(CONF_GET_REQUEST, SessionForms,
                      path='conference/{websafeConferenceKey}/session',
                      http_method='GET', name='getConferenceSessions')
    def getConferenceSessions(self, request):
        """
            Public facing endpoint that gets all the sessions in the datastore
            that have the websafeKey as it's parent.

        :param request object containing
                - websafeConferenceKey: the websafeKey of the Conference to get
                                        the sessions for
        :return: list of SessionForm objects representing the sessions that fit
                 the query
        """

        # Verify the conference exists
        conf = ndb.Key(urlsafe=request.websafeConferenceKey).get()
        if not conf:
            raise endpoints.NotFoundException(
                    'No conference found with key: %s' %
                    request.websafeConferenceKey
            )

        # get the sessions for this conference and return them
        sessions = Session.query(ancestor=conf.key).fetch()
        return SessionForms(
                items=[self._copySessionToForm(session) for session in sessions]
        )

    @endpoints.method(CONF_GET_REQUEST, SessionForms,
                      path='conference/{websafeConferenceKey}/session/schedule',
                      http_method='GET', name='getConferenceSessionsSchedule')
    def getConferenceSessionSchedule(self, request):
        """
            Public facing endpoint for a user to get their "schedule" for a
            conference. I.e. all the sessions in their wishlist, ordered by
            date and start_time

        :param request object containing
                - websafeConferenceKey: the websafeKey of the Conference to get
                                        the sessions for
        :return: list of SessionForm objects representing the sessions that fit
                 the query
        """
        # get user and their sessions
        prof = self._getProfileFromUser()  # get user Profile
        session_keys = [ndb.Key(urlsafe=wssk)
                        for wssk in prof.sessionKeysInWishlist]
        wishlist_sessions = ndb.get_multi(session_keys)

        # get conference and sessions in that conference
        # make sure it's ordered by date and start time.
        conf = ndb.Key(urlsafe=request.websafeConferenceKey).get()
        if not conf:
            raise endpoints.NotFoundException(
                    'No conference found with key: %s' %
                    request.websafeConferenceKey
            )
        q = Session.query(ancestor=conf.key)
        q = q.order(Session.date)
        conf_sessions = q.order(Session.start_time).fetch()

        # throw out all the sessions that aren't on the user's wishlist
        # I'd love to do a JOIN here, but datastore doesn't support it.
        session_list = []
        for cs in conf_sessions:
            for ws in wishlist_sessions:
                if ws.key.urlsafe() == cs.key.urlsafe():
                    session_list.append(ws)

        return SessionForms(
                items=[self._copySessionToForm(session)
                       for session in session_list]
        )

    @endpoints.method(SESSION_DURATION_REQUEST, SessionForms,
                      path='conference/{websafeConferenceKey}/session/duration',
                      http_method='POST', name='getConferenceSessionsByDuration')
    def getConferenceSessionsByDuration(self, request):
        """
            Public facing endpoint for a user to get all the sessions that fit
            the duration requested

        :param request object containing
                - websafeConferenceKey: the websafeKey of the Conference to get
                                        the sessions for
                - minDuration: an integer representing the minimum duration of
                               a session the user is looking for
                - maxDuration: an integer representing the maximum duration of
                               a session the user is looking for
        :return: list of SessionForm objects representing the sessions that fit
                 the query
        """
        conf = ndb.Key(urlsafe=request.websafeConferenceKey).get()
        if not conf:
            raise endpoints.NotFoundException(
                    'No conference found with key: %s' %
                    request.websafeConferenceKey
            )
        q = Session.query(ancestor=conf.key)
        q = q.order(Session.duration)
        q = q.filter(Session.duration > request.minDuration)
        sessions = q.filter(Session.duration < request.maxDuration).fetch()

        return SessionForms(items=[self._copySessionToForm(session)
                                   for session in sessions]
                            )

    @endpoints.method(SESSION_BY_TYPE_GET_REQUEST, SessionForms,
                      path='conference/{websafeConferenceKey}/session/type/{typeOfSession}',
                      http_method='GET', name='getConferenceSessionsByType')
    def getConferenceSessionsByType(self, request):
        """
            Public facing endpoint that gets sessions based on the type for
            a conference

        :param request object containing
                - websafeConferenceKey: the websafeKey of the Conference to
                                        filter to
                - typeOfSession: the session that the user wants to filter to
        :return: list of SessionForm objects representing the sessions that fit
                 the query
        """
        conf = ndb.Key(urlsafe=request.websafeConferenceKey).get()
        if not conf:
            raise endpoints.NotFoundException(
                    'No conference found with key: %s' %
                    request.websafeConferenceKey
            )
        q = Session.query(ancestor=conf.key)
        sessions = q.filter(
                Session.type_of_session == str(request.typeOfSession)
        ).fetch()

        return SessionForms(
                items=[self._copySessionToForm(session) for session in sessions]
        )

    # SESSION Query
    @endpoints.method(message_types.VoidMessage, SessionForms,
                      path='session/noWorkshopsBefore7pm',
                      http_method='GET', name='getSessionsNotWorkshopsBefore7pm')
    def getSessionsNotWorkshopsBefore7pm(self, request):
        """
            Public facing endpoint that filters the sessions to those that are
            not workshops and start before 7pm.

        :param request object which is Void
        :return: list of SessionForm objects representing the sessions that fit
                 the query
        """
        # perform the inequality filter for sessions starting before 7pm
        q = Session.query()
        q = q.order(Session.start_time)
        sessions = q.filter(Session.start_time < 1900).fetch()

        # perform the next "inequality filter" with is an O(n) loop,
        # discarding the sessions that are "workshops"
        response = []
        for session in sessions:
            if session.type_of_session != str(TypeOfSession.WORKSHOP):
                response.append(session)

        return SessionForms(items=[self._copySessionToForm(session)
                                   for session in response]
                            )

    @endpoints.method(SESSION_BY_SPEAKER_GET_REQUEST, SessionForms,
                      path='session/speaker/{speaker}',
                      http_method='GET', name='getSessionsBySpeaker')
    def getSessionsBySpeaker(self, request):
        """
            Public facing endpoint that gets all the sessions in the datastore
            that have a specific speaker

        :param request object containing
                - speaker: the string representing the speaker
        :return: list of SessionForm objects representing the sessions that fit
                    the query
        """

        sessions = Session.query(Session.speaker == request.speaker).fetch()
        return SessionForms(
                items=[self._copySessionToForm(session) for session in sessions]
        )

    # SESSION WISHLIST endpoints
    @endpoints.method(message_types.VoidMessage, SessionForms,
                      path='session/wishlist',
                      http_method='GET', name='getSessionsInWishlist')
    def getSessionsInWishlist(self, request):
        """
            Public facing endpoint used for a user to see what sessions are in
            their wishlist

        :param request object which is Void
        :return: list of SessionForm objects representing the sessions in the
                 user's wishlist
        """
        prof = self._getProfileFromUser()
        session_keys = [ndb.Key(urlsafe=wssk)
                        for wssk in prof.sessionKeysInWishlist]
        sessions = ndb.get_multi(session_keys)

        return SessionForms(
                items=[self._copySessionToForm(session)
                       for session in sessions]
        )

    @endpoints.method(SESSION_WISHLIST_REQUEST, BooleanMessage,
                      path='session/{websafeSessionKey}',
                      http_method='POST', name='addSessionToWishlist')
    def addSessionToWishlist(self, request):
        """
            Public facing endpoint that a user calls when they want to add a
            session to their wishlist

        :param request object containing
                - websafeSessionKey: the websafeKey of the Session to add to
                                     the wishlist
        :return: response of the _sessionWishlist function
        """
        return self._sessionWishlist(request)

    @endpoints.method(SESSION_WISHLIST_REQUEST, BooleanMessage,
                      path='session/{websafeSessionKey}',
                      http_method='DELETE', name='removeSessionFromWishlist')
    def removeSessionFromWishlist(self, request):
        """
            Public facing endpoint that a user calls when they want to remove a
            session from their wishlist

        :param request object containing
                - websafeSessionKey: the websafeKey of the Session to add to
                                     the wishlist
        :return: response of the _sessionWishlist function
        """
        return self._sessionWishlist(request, False)

api = endpoints.api_server([ConferenceApi])  # register API
