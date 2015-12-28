import json
import os
import time
import uuid

from google.appengine.api import urlfetch
from models import Profile


def getUserId(user, id_type="email"):
    if id_type == "email":
        return user.email()

    if id_type == "oauth":
        """A workaround implementation for getting userid."""
        auth = os.getenv('HTTP_AUTHORIZATION')
        bearer, token = auth.split()
        token_type = 'id_token'
        if 'OAUTH_USER_ID' in os.environ:
            token_type = 'access_token'
        url = ('https://www.googleapis.com/oauth2/v1/tokeninfo?%s=%s'
               % (token_type, token))
        user = {}
        wait = 1
        for i in range(3):
            resp = urlfetch.fetch(url)
            if resp.status_code == 200:
                user = json.loads(resp.content)
                break
            elif resp.status_code == 400 and 'invalid_token' in resp.content:
                url = ('https://www.googleapis.com/oauth2/v1/tokeninfo?%s=%s'
                       % ('access_token', token))
            else:
                time.sleep(wait)
                wait = wait + i
        return user.get('user_id', '')

    if id_type == "custom":
        # implement your own user_id creation and getting algorythm
        # this is just a sample that queries datastore for an existing profile
        # and generates an id if profile does not exist for an email
        profile = Conference.query(Conference.mainEmail == user.email())
        if profile:
            return profile.id()
        else:
            return str(uuid.uuid1().get_hex())


def validateTime(time):
    """
        Helper function that checks the value the user entered for time

    :param time: the inputted time from the user
    :return: the time the user entered, or 0
    """
    response = time
    if  (time > 59 and time < 100) or \
        (time > 159 and time < 200) or \
        (time > 259 and time < 300) or \
        (time > 359 and time < 400) or \
        (time > 459 and time < 500) or \
        (time > 559 and time < 600) or \
        (time > 659 and time < 700) or \
        (time > 759 and time < 800) or \
        (time > 859 and time < 900) or \
        (time > 959 and time < 1000) or \
        (time > 1059 and time < 1100) or \
        (time > 1159 and time < 1200) or \
        (time > 1259 and time < 1300) or \
        (time > 1359 and time < 1400) or \
        (time > 1459 and time < 1500) or \
        (time > 1559 and time < 1600) or \
        (time > 1659 and time < 1700) or \
        (time > 1759 and time < 1800) or \
        (time > 1859 and time < 1900) or \
        (time > 1959 and time < 2000) or \
        (time > 2059 and time < 2100) or \
        (time > 2159 and time < 2200) or \
        (time > 2259 and time < 2300) or \
        (time > 2359):
            response = 0
    return response
