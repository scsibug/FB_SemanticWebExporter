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
from os import urandom
foafp = "http://xmlns.com/foaf/0.1/"

# TODO:
# Generic functions to add triples from either friends or myself.
# request users email and foaf:Person URI
# Allow users to show only their info, not their friends.
# Publish aggregate data about # of triples served, unique users, etc.
# Direct links are broken when running web2py multiprocess.
#      Need to store tokens in DB, not cache.

def index():
    require_facebook_login(request,fb_settings)
    start_time = time.time()
    facebook=request.facebook
    reqformat = detect_requested_format()
    graph = cache.ram(facebook.uid, lambda:buildgraph(facebook),time_expire=swe_settings.GRAPH_CACHE_SEC)
    graphserial = graph.serialize(format=reqformat)
    tc = len(graph)
    # Generate a random token for the direct link
    token = cache.ram("token"+facebook.uid, lambda:(urandom(24).encode('hex')),time_expire=swe_settings.GRAPH_CACHE_SEC)
    tripleslink = generate_triples_link(facebook.uid, reqformat, token)
    stop_time = time.time()
    db.served_log.insert(fb_user_id=facebook.uid, triple_count=tc, format=reqformat, processing_ms=(stop_time-start_time)*1000.0, timestamp=datetime.datetime.now())
    return dict(message="Hello "+get_facebook_user(request), graph=graphserial, format=reqformat, count=tc, tripleslink=tripleslink, baseurl=swe_settings.CANVAS_BASE_URL)

def detect_requested_format():
    reqformat=request.vars.format
    if (reqformat != 'n3' and reqformat != 'rdf' and reqformat != 'nt' and reqformat != 'turtle'):
        reqformat = 'rdf'
    return reqformat

# Generate an absolute link to raw triples, for direct downloads.
def generate_triples_link(uid, format, token):
    if not format:
        format = 'rdf'
    if token and uid:
        return swe_settings.SERVER_APP_URL + 'default/triples?' + 'token=' + token + '&uid=' + uid + '&format=' + format
    else:
        return ""

def triples():
    token = request.vars.token
    fb_uid = request.vars.uid
    real_token = cache.ram("token"+fb_uid, lambda:(urandom(24).encode('hex')),time_expire=swe_settings.GRAPH_CACHE_SEC)
    reqformat = detect_requested_format()
    if (real_token == token):
        if reqformat not in ['rdf', 'n3', 'nt', 'turtle']:
            reqformat = 'rdf'
        # pull the graph out of the cache
        graph = cache.ram(fb_uid, lambda:buildgraph())
        graphserial = graph.serialize(format=reqformat)
        if reqformat == 'rdf':
            response.headers["Content-Type"] = "application/rdf+xml; charset=utf-8"
            response.headers["Content-disposition"] = "attachment; filename=foaf.rdf"
        elif reqformat == 'n3':
            response.headers["Content-Type"] = "text/n3"
            response.headers["Content-disposition"] = "attachment; filename=foaf.n3"
        elif reqformat == 'nt': # N-Triples are ASCII
            response.headers["Content-Type"] = "text/plain"
            response.headers["Content-disposition"] = "attachment; filename=foaf.nt"
        elif reqformat == 'turtle': # Turtle is UTF-8 always
            response.headers["Content-Type"] = "application/x-turtle"
            response.headers["Content-disposition"] = "attachment; filename=foaf.ttl"
        return graphserial            

    else:
        return "Not authorized, or this link has expired."
    
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
    if not facebook:
        return
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
