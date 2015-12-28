#!/usr/bin/env python

"""
main.py -- Udacity conference server-side Python App Engine
    HTTP controller handlers for memcache & task queue access

$Id$

created by wesc on 2014 may 24

"""

__author__ = 'wesc+api@google.com (Wesley Chun)'

import webapp2
from google.appengine.api import app_identity
from google.appengine.api import mail
from conference import ConferenceApi

class SetAnnouncementHandler(webapp2.RequestHandler):
    """Handler for setting the annoucement"""
    def get(self):
        """Set Announcement in Memcache."""
        ConferenceApi._cacheAnnouncement()
        self.response.set_status(204)


class SendConfirmationEmailHandler(webapp2.RequestHandler):
    """Handler to send email confirmation"""
    def post(self):
        """Send email confirming Conference creation."""
        mail.send_mail(
            'noreply@%s.appspotmail.com' % (
                app_identity.get_application_id()),     # from
            self.request.get('email'),                  # to
            'You created a new Conference!',            # subj
            'Hi, you have created a following '         # body
            'conference:\r\n\r\n%s' % self.request.get(
                'conferenceInfo')
        )

class SetFeaturedSpeakerHandler(webapp2.RequestHandler):
    """Handler to set the featured speaker"""
    def post(self):
        """admin accessible request handler used to set the featured speaker"""
        ConferenceApi._setFeaturedSpeaker(self.request.get('speaker'),
                                          self.request.get('wsck'))



app = webapp2.WSGIApplication(
    [
        ('/crons/set_announcement', SetAnnouncementHandler),
        ('/tasks/send_confirmation_email', SendConfirmationEmailHandler),
        ('/tasks/set_featured_speaker', SetFeaturedSpeakerHandler),
    ],
    debug=True)

