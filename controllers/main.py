from applications.sw_exporter.modules.facebook import *
from applications.sw_exporter.modules.settings import swe_settings, fb_settings

import datetime
import time
import rdflib
from rdflib import Graph
from rdflib import plugin
from rdflib.store import Store, NO_STORE, VALID_STORE
from rdflib import Namespace
from rdflib import Literal
from rdflib import BNode
from rdflib import URIRef
from rdflib.constants import TYPE, VALUE
from rdflib.TripleStore import TripleStore

foafp = "http://xmlns.com/foaf/0.1/"

# TODO:
# strip out spaces/newlines/&#10 from websites attribute (make separate website properties)
# deal with websites that start with "www"
# Generic functions to add triples from either friends or myself.
# request users email and foaf:Person URI
# Allow users to show only their info, not their friends.
# Direct links to triples, for saving.
# Publish aggregate data about # of triples served, unique users, etc.

def index():
    require_facebook_login(request,fb_settings)
    start_time = time.time()
    facebook=request.facebook
    reqformat=request.vars.format
    if (reqformat != 'n3' and reqformat != 'rdf' and reqformat != 'nt' and reqformat != 'turtle'):
        reqformat = 'rdf'
    graph = cache.ram(facebook.uid, lambda:buildgraph(facebook),time_expire=swe_settings.GRAPH_CACHE_SEC)
    graphserial = graph.serialize(format=reqformat)
    tc = len(graph)
    stop_time = time.time()
    db.served_log.insert(fb_user_id=facebook.uid, triple_count=tc, format=reqformat, processing_ms=(stop_time-start_time)*1000.0, timestamp=datetime.datetime.now())
    d = dict(message="Hello "+get_facebook_user(request), graph=graphserial, format=reqformat, count=tc)
    return response.render(d)

# Take an RDF graph, foaf-user URI, and the facebook "website" field,
# and try to extract some meaningful URIs.  People often put multiple
# space/newline delimited websites in this field, and leave off the
# scheme (http://).
def sanitize_websites(graph, user, website_field):
    # get a list of whitespace-delimited items in the website field
    websites = website_field.split()
    # Assume all websites start with "http://"
    for website in websites:
        # Strip off trailing characters more likely to be used in a list of
        # entries than to end a valid URL
        website = website.rstrip(',;')
        if website.startswith("http://") or website.startswith("https://"):
            graph.add((user,URIRef(foafp+"homepage"),URIRef(website)))
        elif website.startswith("www"):
            graph.add((user,URIRef(foafp+"homepage"),URIRef("http://"+website)))
        elif (".com" in website) or (".net" in website) or (".org" in website):
            graph.add((user,URIRef(foafp+"homepage"),URIRef("http://"+website)))
        # Text is too sketchy to try and url-ize.

def buildgraph(facebook):
    # Create an in-memory store
    graph = Graph()
    # Setup prefixes
    graph.bind("foaf", foafp)
    # Add a relative URIRef to "myself"
    # TODO: give the option to provide an absolute URI
    me = URIRef("#me")
    graph.add((me, TYPE, URIRef(foafp+"Person")))
    # Fetch more information about "myself"
    query = "SELECT uid, first_name, last_name, pic, sex, current_location, profile_url, website FROM user WHERE uid=%s" % facebook.uid
    results = facebook.fql.query(query)[0]
    first_name = results[u'first_name']
    last_name = results[u'last_name']
    name = first_name+' '+last_name
    graph.add((me, URIRef(foafp+"givenName"), Literal(first_name)))
    graph.add((me, URIRef(foafp+"familyName"), Literal(last_name)))
    graph.add((me, URIRef(foafp+"name"), Literal(name)))
    sex = results[u'sex']
    if sex :
        graph.add((me, URIRef(foafp+"gender"), Literal(sex)))

    pic = results[u'pic']
    if pic :
        graph.add((me, URIRef(foafp+"img"), URIRef(pic)))

    website = results[u'website']
    if website :
        sanitize_websites(graph, me, website)

    # Build facebook account info
    # the "account" is blank
    myaccount = BNode()
    graph.add((me, URIRef(foafp+"account"), myaccount))
    graph.add((myaccount, TYPE, URIRef(foafp+"OnlineAccount")))
    graph.add((myaccount, URIRef(foafp+"accountName"), Literal(name)))
    graph.add((myaccount, URIRef(foafp+"accountProfilePage"), URIRef(results[u'profile_url'])))
    graph.add((myaccount, URIRef(foafp+"accountServiceHomepage"), URIRef("http://www.facebook.com/")))
    # Find all friends
    friendquery = "SELECT uid, first_name, last_name, pic, sex, current_location, profile_url, website FROM user WHERE uid IN (SELECT uid2 FROM friend WHERE uid1 = %s)" % facebook.uid
    friendresults = facebook.fql.query(friendquery)

    for fresult in friendresults:
        thisfriend = BNode()
        graph.add((myaccount, URIRef(foafp+"knows"), thisfriend))
        ffirst_name = fresult[u'first_name']
        flast_name = fresult[u'last_name']
        fname = ffirst_name+' '+flast_name
        fsex = fresult[u'sex']
        if ffirst_name:
            graph.add((thisfriend, URIRef(foafp+"givenName"), Literal(ffirst_name)))
        if flast_name:
            graph.add((thisfriend, URIRef(foafp+"familyName"), Literal(flast_name)))
        if fname:
            graph.add((thisfriend, URIRef(foafp+"name"), Literal(fname)))
        if fsex:
            graph.add((thisfriend, URIRef(foafp+"gender"), Literal(fsex)))
        fpic = fresult[u'pic']
        if fpic :
            graph.add((thisfriend, URIRef(foafp+"img"), URIRef(fpic)))

        fwebsite = fresult[u'website']
        if fwebsite :
            sanitize_websites(graph, thisfriend, fwebsite)
        friendaccount = BNode()
        graph.add((thisfriend, URIRef(foafp+"account"), friendaccount))
        graph.add((friendaccount, TYPE, URIRef(foafp+"OnlineAccount")))
        graph.add((friendaccount, URIRef(foafp+"accountName"), Literal(fname)))
        graph.add((friendaccount, URIRef(foafp+"accountProfilePage"), URIRef(fresult[u'profile_url'])))
        graph.add((friendaccount, URIRef(foafp+"accountServiceHomepage"), URIRef("http://www.facebook.com/")))
    return graph
