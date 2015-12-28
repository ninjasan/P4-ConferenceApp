App Engine application for the Udacity training course.

## Products
- [App Engine][1]

## Language
- [Python][2]

## APIs
- [Google Cloud Endpoints][3]

## Thanks
- Shout out to the Udacity course "Developing Scalable Apps in Python" which 
    provided the starting point for the conference central app.

## Setup Instructions
If you want to deploy this app on your own follow these steps
    1. Create your own google project - following the steps described in the
       "Developing Scalable Apps in Python" course, Lesson 2, video 3.
       https://www.udacity.com/course/viewer#!/c-ud858-nd/l-3887428705/m-1400398679
    2. Get your environment set-up by following the steps described in the
       "Developing Scalable Apps in Python" course, Lesson 2, video 7.
       https://www.udacity.com/course/viewer#!/c-ud858-nd/l-3887428705/e-3968628722/m-3943158840
    3. Clone the repository
        https://github.com/ninjasan/P4-ConferenceApp.git
    4. Update values
        - Update the value of `application` in `app.yaml` to the app ID you
          have registered in the App Engine admin console and would like to use 
          to host your instance of this sample.
        - Update the values at the top of `settings.py` to reflect the 
          respective client IDs you have registered in the 
          [Developer Console][4].
        - Update the value of CLIENT_ID in `static/js/app.js` to the Web 
          client ID
    5. (Optional) Mark the configuration files as unchanged as follows:
       `$ git update-index --assume-unchanged app.yaml settings.py static/js/app.js`
    6. Launch GoogleAppEngineLauncher
        - Add an existing application
            - Go to File->Add Existing Application
            - Enter the path to where you cloned the repository
            - Make note of the Port and admin port (default port is 8080)
            - Click add 
    7. Highlight the new row that was just created and click run.
        - Verify the deployment was successful by clicking "Logs"
    8. Deploy to your project by clicking Deploy

If you want to simply use the existing deployment without needing to deploy
the project yourself, visit this location:
https://apis-explorer.appspot.com/apis-explorer/?base=https://scalable-web-app-1156.appspot.com/_ah/api#p/

## Design decisions
### Classes
- Session:  The Session model contains the fields described in the project
            details. The text fields are StringProperties (name, highlights,
            speaker, and the type of the session). The speaker is a repeated
            field, in case there are multiple speakers in the session. It's just
            a repeated string, and not an profile entity. Nor did I create a 
            whole new speaker entity type. I could have make a speaker entity
            but chose to stick with simplicity. The type of the session is an
            enum. I debated over making it a simple text field, but making it 
            an enum allows for some consistency. The duration, start_time, and
            conference_id are integers. I chose to make the session a child of a
            conference, it makes sense for sessions to be part of a conference. 
            Sessions aren't just free-floating entities in space and it doesn't 
            make sense for a session to be applicable to any conference. Because
            of that reasoning, I chose to make sessions children of conferences.
            The start_time is intended to be in military notation. Then the date
            of the session is a Date in the model. To create a Session, you just
            need to provide the name. Other fields get some default values 
            (based on the conference.py code, not the model).
- SessionForm: The SessionForm message object contains all the same fields
            as the Session. Here the enum for type_of_session is enforced. Also,
            since the start_time is intended to be in military time, only
            unsigned-ints are valid. Then the Form also contains the websafeKey
            that for the session, so that a caller can get the key to make
            other calls based on that key.
- SessionForms: The SessionForms message is just a repeated SessionForm message
            object. That way, more than one SessionForm can be returned in the
            app.
- TypeOfSession: I chose to implement an enum for Session types to enforce
            some bit of conformity across sessions.

### Endpoints
#### Task 1 - session basics
- createSession: The createSession method takes the SessionForm and
            websafeConferenceKey provided by the user and passes it along to a
            private method to perform the actual datastore updating logic.
            Within _createSessionObject()_, the user is validated (i.e. we make
            sure the user is authenticated and has authorization to update this
            conference. Here, I also validate that the time the user inputted
            is valid military time. I.e. 1230 is valid, but 1260 is not. Any 
            fields that the user doesn't provide (and wasn't a required field)
            gets a default field from the global variable. After generating the
            needed ids/keys, the new data is put into a Session object in the 
            datastore. I wait until after creating the session object before
            starting a task to check for featured speakers, and then return
            the SessionForm with the data the user specified. (Note, I also
            chose to make a helper function that copied objects to SessionForms
            so I didn't have to repeat the code everywhere.)
- getConferenceSessions: The endpoint first validates that the 
            websafeConferenceKey is valid and then fetches the sessions that
            have that conference as it's ancestor.
- getConferenceSessionsByType: The endpoint first validates that the
            websafeConferenceKey is valid and then fetches the sessions that
            have that conferenece as it's ancestor, as well as filters to the
            enum.
- getSessionsBySpeaker: This endpoint doesn't look for a sessions in a specific
            conference, it just looks for any session with a certain speaker as
            at least one of the speakers in the repeated speaker field. I chose
            to allow this because if a user just wants to see sessions that
            contain a certain person, then enforcing that the person is the only
            speaker doesn't make sense, other wise the user might miss panels or
            something where the speaker is one of the speakers, but not the only
            speaker.
#### Task 2 - wishlist
- addSessionToWishlist: Here, a user can add a session to their wishlist without
            having already registered for the conference. The reason is that
            this is called the user's wishlist, not their registered sessions.
            For a wishlist, I wanted the user to be able to save sessions that
            sound interesting to them. That way, they can review their wishlist
            and see if there are certain conferences they definitely need to
            attend (because they've saved a large number of sessions from that
            conference to their wishlist). If you can only save sessions in
            conferences you've already registered for, then it would be harder
            for the user to compare/contrast how interesting they feel the
            sessions are without doing more work manually.
- getSessionsInWishlist: Along with the explanation above, all sessions in the 
            wishlist are returned, instead of just for one conference.
- removeSessionFromWishlist: I added this method because it's possible a user
            may decide they aren't really interested in a session. It doesn't
            make sense to force them to keep it on their wishlist.
#### Task 3 - queries & indices
- getConferenceSessionSchedule: To go along with the idea of helping user's
            decide what Conferences they'd like to go to, I wanted to create an
            endpoint that gave the user a list of the sessions for a certain
            conference saved to their wishlist, but ordered by both date and
            start_time. This was tricky. Ideally, I'd get the user's wishlist
            as a query, so I can then order the query by date and start_time, 
            and filter to a specific conference_id. But you can't do that with
            datastore. So, I chose to get the wishlist - which returns a list
            with get_multi. I also got the entire session list for a conference
            and ordered that by date and start_time. Here again, I'd love to do
            a inner join, so that I'd only get the conference sessions that are
            also in the user's wishlist, but again, datastore doesn't support
            that. Instead, I did "join" manually, by looking matches in session
            keys.
- getConferenceSessionsByDuration: Again, going along with the idea of helping
            the user find sessions they might be interested in, I wrote this
            endpoint that allows a user to specify the duration they'd be
            interested in. For example, if you lose interest quickly, longer
            sessions are not ideal. Here, the user can provide a minduration and
            maxduration, as well as the websafeConferenceKey to see all the
            sessions that fit those requirements in a Conference. While the
            query has two inequalities, they are targeted to the same field, so
            the query still works.
- getSessionsNotWorkshopsBefore7pm: This endpoint implements the project in the
            problem "Let’s say that you don't like workshops and you don't like
            sessions after 7 pm. How would you handle a query for all 
            non-workshop sessions before 7 pm? What is the problem for 
            implementing this query? What ways to solve it did you think of?"
            The problem with this query is that datastore doesn't support two
            inequality filters on two different fields. Here, it would be on
            type_of_session, and on start_time. My implemented solution was to
            break to the query into two parts. I did part of the work by using a
            query to get all sessions before 7pm (i.e. 1900). Then I looped over
            the results to filter out the workshops that may be left. This is 
            not really ideal because it adds O(n) to the runtime of the 
            endpoint. This could be a problem if the session list is very large.
            Other solutions include not using datastore and using a relational
            database instead. It may slow down the app, but there are abilities
            in a relational database. Or you can implement a relational database
            with a caching layer to speed up the queries. Another solution 
            would be to create a field in the Session object that combined the 
            type_of_session and start_time. Though, that filter query would be
            complicated. Another potential solution would be to create a boolean
            field at the time of creating the session object. If a person knew
            ahead of time that this was a super important query for the users,
            the boolean could be set to true for any Session that was not a
            workshop and started before 7pm. Then, the query just would need to
            filter to sessions where that boolean was True. I chose not to
            implement that solution because that could get out of hand (if every
            special query needed it's own boolean).
#### Task 4 - featured speakers
- getFeaturedSpeaker: This endpoint simply looks for the memcache key 
            representing the featured speaker.
- Task to setFeaturedSpeaker: When a session is created, the task is created.
            The task calls the admin-only handler, which calls the private
            helper function. The helper function gets all the sessions for a
            specific websafeConferenceKey by a speaker. If the number of 
            sessions is greater than 1, then the memcache key is updated. In 
            case where the newest session has multiple speakers, then I chose
            to only focus on the first speaker listed as I assume that the 
            first speaker listed is the "most important".

[1]: https://developers.google.com/appengine
[2]: http://python.org
[3]: https://developers.google.com/appengine/docs/python/endpoints/
[4]: https://console.developers.google.com/
[5]: https://localhost:8080/
[6]: https://developers.google.com/appengine/docs/python/endpoints/endpoints_tool
