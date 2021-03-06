# -*- coding: utf-8 -*-createacsr_handler
from __future__ import unicode_literals

import json
import logging
import os
import uuid
import time
import secrets
import base64

import cryptography
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes

from flask import abort
from flask import Flask, redirect
from flask import request
from flask import Response
from flask import render_template
from jinja2.exceptions import TemplateNotFound

from jwcrypto import jwk, jwt
import requests

from werkzeug.contrib.cache import SimpleCache

# ENV vars
FLASK_DEBUG = os.getenv('FLASK_DEBUG', True)
TEMPLATES_FOLDER = os.getenv('TEMPLATES_FOLDER', './templates')
CACHE_TIMEOUT = int(os.getenv('CACHE_TIMEOUT', 300))

TEST_API_ENDPOINT = os.getenv('TEST_API_ENDPOINT')

DIRECTORY_ENDPOINT = os.getenv('DIRECTORY_ENDPOINT', 'http://localhost:3000')

if FLASK_DEBUG:
    # configure requests logging

    import http.client as http_client

    http_client.HTTPConnection.debuglevel = 1
    logging.basicConfig()
    logging.getLogger().setLevel(logging.DEBUG)
    logger = logging.getLogger(__name__)
    requests_log = logging.getLogger("requests.packages.urllib3")
    requests_log.setLevel(logging.DEBUG)
    requests_log.propagate = True

app = Flask(__name__, template_folder=TEMPLATES_FOLDER)
app.debug = FLASK_DEBUG

# Setting SECRET_KEY
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', secrets.token_hex(16))

cache = SimpleCache()

################################################################################
# Utilities
################################################################################

def make_private_key(key_size: int) -> bytes:
    """Return an RSA private key

    :param key_size:
    :return key:
    """
    key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=key_size,
        backend=default_backend()
    )
    return key


def make_private_key_pem(private_key: bytes) -> str:
    """Convert RSA private key to PEM format

    :param private_key:
    :return pem:
    """
    pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption()
    )
    return pem


def make_csr(private_key: bytes) -> str:
    """Return a CSR based on the given private key.

    :param private_key:
    :return csr:
    """
    csr = x509.CertificateSigningRequestBuilder().subject_name(
        x509.Name(
            [
                x509.NameAttribute(NameOID.COUNTRY_NAME, cache.get('csr_country_name') or 'GB'),
                x509.NameAttribute(NameOID.STATE_OR_PROVINCE_NAME,
                                   cache.get('csr_state_or_province_name') or 'Middlesex'),
                x509.NameAttribute(NameOID.LOCALITY_NAME, cache.get('csr_locality_name') or 'London'),
                x509.NameAttribute(NameOID.ORGANIZATIONAL_UNIT_NAME,
                                   cache.get('csr_organizational_unit_name') or 'My TPP'),
                x509.NameAttribute(NameOID.COMMON_NAME, cache.get('csr_common_name') or 'IT'),
            ]
        )
    ).sign(private_key, hashes.SHA256(), default_backend())
    return csr


def make_jwk_from_pem(private_pem: str) -> dict:
    """Convert a PEM into a JWK

    :param private_pem:
    :return jwk_dict:
    """

    jwk_dict = dict()

    try:
        key_obj = jwk.JWK.from_pem(private_pem.encode('latin-1'))
    except Exception as e:
        app.logger.debug('{}'.format(e))
    else:
        jwk_dict = json.loads(key_obj.export())
        jwk_dict['kid'] = key_obj.thumbprint(hashalg=cryptography.hazmat.primitives.hashes.SHA1())
        jwk_dict['x5t'] = key_obj.thumbprint(hashalg=cryptography.hazmat.primitives.hashes.SHA1())
        jwk_dict['x5t#256'] = key_obj.thumbprint(hashalg=cryptography.hazmat.primitives.hashes.SHA256())
    return jwk_dict


def make_token(kid: str, software_statement_id: str, client_scopes: str, token_url: str) -> str:
    jwt_iat = int(time.time())
    jwt_exp = jwt_iat + 3600
    header = dict(alg='RS256', kid=kid, typ='JWT')
    claims = dict(
        iss=software_statement_id,
        sub=software_statement_id,
        scopes=client_scopes,
        aud=token_url,
        jti=str(uuid.uuid4()),
        iat=jwt_iat,
        exp=jwt_exp
    )

    token = jwt.JWT(header=header, claims=claims)
    key_obj = jwk.JWK.from_pem(cache.get('signing_private_key_pem').encode('latin-1'))
    token.make_signed_token(key_obj)
    signed_token = token.serialize()
    return signed_token


def make_onboarding_token(kid: str, iss: str, aud: str, sub: str, scope: str, client_id: str, ssa: str) -> str:
    jwt_iat = int(time.time())
    jwt_exp = jwt_iat + 3600
    header = dict(alg='RS256', kid=kid, typ='JWT')
    claims = dict(
        iss=iss,
        iat=jwt_iat,
        exp=jwt_exp,
        aud=aud,
        sub=sub,
        scope=scope,
        token_endpoint_auth_method='private_key_jwt',
        grant_types=['authorization_code', 'refresh_token', 'client_credentials'],
        response_types=['code', 'id_token'],
        client_id=client_id,
        software_statement=ssa
    )

    token = jwt.JWT(header=header, claims=claims)
    key_obj = jwk.JWK.from_pem(cache.get('signing_private_key_pem').encode('latin-1'))
    token.make_signed_token(key_obj)
    signed_token = token.serialize()
    return signed_token


def create_csr(purpose, key_size):
    private_key = make_private_key(key_size)
    private_key_pem = make_private_key_pem(private_key).decode(encoding='utf-8')
    cache.set(f"{purpose}_private_key_pem", private_key_pem, timeout=CACHE_TIMEOUT)

    csr = make_csr(private_key)
    csr_pem = csr.public_bytes(serialization.Encoding.PEM).decode(encoding='utf-8')
    cache.set(f"{purpose}_csr", csr_pem, timeout=CACHE_TIMEOUT)

def base64_encode_image(brand_image_location) -> bytes:
    
    with open(brand_image_location, "rb") as image:
        b64string = base64.b64encode(image.read())
        return b64string    

def get_context() -> dict:

    context = dict()

    # Home /
    context['scheme'] = cache.get('scheme')
    context['org_name'] = cache.get('org_name')
    context['tpp_id'] = cache.get('tpp_id')
    context['type'] = cache.get('type')
    context['domain'] = cache.get('domain')
    context['software_statement_id'] = cache.get('software_statement_id')
    context['client_scopes'] = cache.get('client_scopes')
    context['onboarding_scopes'] = cache.get('onboarding_scopes')
    context['token_url'] = os.path.join(DIRECTORY_ENDPOINT, 'token')
    context['tpp_ssa_url'] = os.path.join(DIRECTORY_ENDPOINT, 'generate')
    context['aspsp_list_url'] = os.path.join(DIRECTORY_ENDPOINT, 'authorization-servers')

    # Private key settings
    context['key_size'] = cache.get('key_size')

    # CSR settings
    context['csr_common_name'] = cache.get('csr_common_name')
    context['csr_organizational_unit_name'] = cache.get('csr_organizational_unit_name')
    context['csr_country_name'] = cache.get('csr_country_name')
    context['csr_state_or_province_name'] = cache.get('csr_state_or_province_name')
    context['csr_locality_name'] = cache.get('csr_locality_name')

    # Certs
    context['signing_private_key_pem'] = cache.get('signing_private_key_pem')
    context['kid'] = make_jwk_from_pem(context['signing_private_key_pem']).get('kid')
    context['signing_csr'] = cache.get('signing_csr')
    context['signing_certificate'] = cache.get('signing_certificate')
    context['transport_private_key_pem'] = cache.get('transport_private_key_pem')
    context['transport_csr'] = cache.get('transport_csr')
    context['transport_certificate'] = cache.get('transport_certificate')

    # Access token
    context['access_token'] = cache.get('access_token')

    # SSA
    context['software_statement_assertion'] = cache.get('software_statement_assertion')

    # Authorization servers
    context['authorization_servers'] = cache.get('authorization_servers')

    # App onboarding
    context['app_onboarding_status_exception'] = cache.get('app_onboarding_status_exception')
    context['app_onboarding_status_url'] = cache.get('app_onboarding_status_url')
    context['app_onboarding_status_code'] = cache.get('app_onboarding_status_code')
    context['app_onboarding_reason'] = cache.get('app_onboarding_reason')
    context['app_onboarding_text'] = cache.get('app_onboarding_text')

    return context


################################################################################
# Route handlers
################################################################################

# / handler
@app.route('/', endpoint='root_handler', methods=['GET', 'POST'])
def root_handler() -> Response:
    """Home / handler
    """

    if request.method == 'POST':
        
        if request.form.get('type') == 'broker':
            f = request.files['brand_image']
            sfname = 'static/img/'+str(f.filename)
            f.save(sfname)
            base64_image = base64_encode_image(sfname)
            os.remove(sfname)
            cache.set('base64_image', base64_image)

        cache.set('scheme', request.form.get('scheme'), timeout=CACHE_TIMEOUT)
        cache.set('org_name', request.form.get('org_name'), timeout=CACHE_TIMEOUT)
        cache.set('tpp_id', request.form.get('tpp_id'), timeout=CACHE_TIMEOUT)
        cache.set('type', request.form.get('type'), timeout=CACHE_TIMEOUT) # Broker, IDP etc
        cache.set('domain', request.form.get('domain'), timeout=CACHE_TIMEOUT)
        cache.set('loa', request.form.get('loa'), timeout=CACHE_TIMEOUT)
        cache.set('software_statement_id', request.form.get('software_statement_id'), timeout=CACHE_TIMEOUT)
        cache.set('client_scopes', request.form.get('client_scopes'), timeout=CACHE_TIMEOUT)
        cache.set('onboarding_scopes', request.form.get('onboarding_scopes'), timeout=CACHE_TIMEOUT)
        cache.set('token_url', request.form.get('token_url'), timeout=CACHE_TIMEOUT)
        cache.set('tpp_ssa_url', request.form.get('tpp_ssa_url'), timeout=CACHE_TIMEOUT)
        cache.set('aspsp_list_url', request.form.get('aspsp_list_url'), timeout=CACHE_TIMEOUT)

        cache.set('csr_pem', '', timeout=CACHE_TIMEOUT)
        cache.set('signing_private_key_pem', '', timeout=CACHE_TIMEOUT)
        cache.set('transport_private_key_pem', '', timeout=CACHE_TIMEOUT)
        cache.set('kid', secrets.token_hex(16), timeout=CACHE_TIMEOUT)



        requests.post(
            os.path.join(DIRECTORY_ENDPOINT, 'organisation', cache.get('type')),
            data=dict(
                scheme=cache.get('scheme'),
                organisation_name=cache.get('org_name'),
                client_id=cache.get('tpp_id'),
                domain=cache.get('domain'),
                csr_pem=cache.get('csr_pem'),
                brand_image=cache.get('base64_image') if cache.get('type') == 'broker' else None,
                loa=cache.get('loa') if cache.get('type') == 'idp' else None
            )
        )
        return redirect('/createcsr', code=302)
    else:
        try:
            return render_template('home.html', context=dict(settings=get_context()))
        except TemplateNotFound:
            abort(404)

# create a csr handler
@app.route('/createcsr/', endpoint='createacsr_handler', methods=['GET', 'POST'])
def createacsr_handler() -> Response:
    """Private key & CSR creation handler.
    """

    if request.method == 'POST':
        cache.set('key_size', request.form.get('key_size'), timeout=CACHE_TIMEOUT)
        cache.set('csr_country_name', request.form.get('csr_country_name'), timeout=CACHE_TIMEOUT)
        cache.set('csr_state_or_province_name', request.form.get('csr_state_or_province_name'), timeout=CACHE_TIMEOUT)
        cache.set('csr_locality_name', request.form.get('csr_locality_name'), timeout=CACHE_TIMEOUT)
        cache.set('csr_organizational_unit_name', request.form.get('tpp_id'), timeout=CACHE_TIMEOUT)
        cache.set('csr_common_name', request.form.get('software_statement_id'), timeout=CACHE_TIMEOUT)

        key_size = int(request.form.get('key_size'))
        create_csr('signing', key_size)
        create_csr('transport', key_size)

        requests.post(
            os.path.join(DIRECTORY_ENDPOINT, 'client-csr'),
            data=dict(
                client_id=cache.get('tpp_id'),
                ssa_id=cache.get('software_statement_id'),
                signing_csr=cache.get('signing_csr'),
                signing_private_key=cache.get('signing_private_key_pem'),
                transport_csr=cache.get('transport_csr'),
                transport_private_key=cache.get('transport_private_key_pem')
            )
        )

        r = requests.get(
            os.path.join(
                DIRECTORY_ENDPOINT,
                'organisation',
                cache.get('type'),
                cache.get('tpp_id'),
                'certificates'
            )
        )

        if r.status_code == 200:
            cache.set('signing_certificate', r.json().get('signing'), timeout=CACHE_TIMEOUT)
            cache.set('transport_certificate', r.json().get('transport'), timeout=CACHE_TIMEOUT)
        else:
            cache.set('signing_certificate', '', timeout=CACHE_TIMEOUT)
            cache.set('transport_certificate', '' , timeout=CACHE_TIMEOUT)

    context = dict(settings=get_context())

    try:
        return render_template('createcsr.html', context=context)
    except TemplateNotFound:
        abort(404)

# obtain an access token from OB
@app.route('/getaccesstoken/', endpoint='createatoken_handler', methods=['GET', 'POST'])
def createatoken_handler() -> Response:
    """Access Token handler
    """
    kid = cache.get('kid')
    if request.method == 'POST':

        kid = request.form.get('kid')
        cache.set('kid', kid, timeout=CACHE_TIMEOUT)

        if cache.get('kid') and cache.get('software_statement_id') and cache.get('client_scopes') and cache.get(
                'token_url'):
            signed_token = make_token(
                cache.get('kid'),
                cache.get('software_statement_id'),
                cache.get('client_scopes'),
                cache.get('token_url')
            )
            cache.set('signed_token', signed_token, timeout=CACHE_TIMEOUT)

            data_dict = dict(
                client_assertion_type='urn:ietf:params:oauth:client-assertion-type:jwt-bearer',
                grant_type='client_credentials',
                client_id=cache.get('tpp_id'),
                client_assertion=cache.get('signed_token'),
                scope=cache.get('client_scopes')
            )
            r = requests.post(cache.get('token_url'), data=data_dict)
            if r.status_code == 200:
                cache.set('access_token', r.json().get('access_token'), timeout=CACHE_TIMEOUT)
            else:
                cache.set('access_token', '', timeout=CACHE_TIMEOUT)

    context = dict(settings=get_context())
    context['settings']['kid'] = kid

    try:
        return render_template('createtoken.html', context=context)
    except TemplateNotFound:
        abort(404)


# get SSA
@app.route('/getssa/', endpoint='getssa_handler', methods=['GET', 'POST'])
def getssa_handler() -> Response:
    """Software Statement Assertion retrieval"""

    if request.method == 'POST':

        try:
            r = requests.get(
                os.path.join(
                    DIRECTORY_ENDPOINT,
                    'organisation',
                    cache.get('type'),
                    cache.get('tpp_id'),
                    'software-statement'
                ),
                headers=dict(
                    Authorization='Bearer {}'.format(
                        cache.get('access_token')
                    )
                ),
                data=dict(ssa_id=cache.get('software_statement_id'))
            )

        except Exception as e:
            app.logger.error('Could not retrieve the SSA because: {}'.format(e))

        else:
            if r.status_code == 200:
                cache.set('software_statement_assertion', r.text, timeout=CACHE_TIMEOUT)
            else:
                app.logger.error('Could not retrieve the SSA, because: {}, {}'.format(r.status_code, r.reason))

    context = dict(settings=get_context())

    try:
        return render_template('getssa.html', context=context)
    except TemplateNotFound:
        abort(404)


# get authorization servers
@app.route('/getauthservers/', endpoint='getauthservers_handler', methods=['GET', 'POST'])
def getauthservers_handler() -> Response:
    """Authorization server list retrieval handler
    """

    if request.method == 'POST':

        try:
            r = requests.get(
                cache.get('aspsp_list_url'),
                headers=dict(
                    Authorization='Bearer {}'.format(
                        cache.get('access_token')
                    )
                )
            )

        except Exception as e:
            app.logger.error('Could not retrieve the list of authorization servers, because: {}'.format(e))

        else:
            if r.status_code == 200:
                auth_servers_resources = r.json().get('Resources')
                if auth_servers_resources:
                    auth_servers_list = [auth_server.get('AuthorisationServers') for auth_server in
                                         auth_servers_resources if auth_server.get('AuthorisationServers')]
                    cache.set('authorization_servers', auth_servers_list, timeout=CACHE_TIMEOUT)
            else:
                app.logger.error(
                    'Could not retrieve the list of authorization servers, because: {}, {}'.format(
                        r.status_code,
                        r.reason
                    )
                )
    context = dict(settings=get_context())

    try:
        return render_template('getauthservers.html', context=context)
    except TemplateNotFound:
        abort(404)


# onboard app
@app.route('/onboard/', endpoint='onboardapp_handler', methods=['GET', 'POST'])
def onboardapp_handler() -> Response:
    """App Onboarding handler.
    """

    if request.method == 'POST':

        headers = dict()
        headers['Content-Type'] = 'application/jwt'
        headers['Accept'] = 'application/json'

        try:
            r = requests.post(
                request.form.get('authorization_server'),
                headers=headers,
                data=make_onboarding_token(
                    kid=cache.get('kid'),
                    iss=cache.get('tpp_id'),
                    aud=request.form.get('authorization_server'),
                    sub=cache.get('software_statement_id'),
                    scope=cache.get('onboarding_scopes'),
                    client_id=cache.get('software_statement_id'),
                    ssa=cache.get('software_statement_assertion')
                )
            )

        except Exception as e:
            app.logger.error('Could not onboard the application, because: {}'.format(e))
            cache.set('app_onboarding_status_exception', 'Could not onboard the application, because: {}'.format(e),
                      timeout=CACHE_TIMEOUT)

        else:
            cache.set('app_onboarding_status_url', r.url, timeout=CACHE_TIMEOUT)
            cache.set('app_onboarding_status_code', r.status_code, timeout=CACHE_TIMEOUT)
            cache.set('app_onboarding_reason', r.reason, timeout=CACHE_TIMEOUT)
            cache.set('app_onboarding_text', r.text, timeout=CACHE_TIMEOUT)

    context = dict(settings=get_context())

    try:
        return render_template('onboardapp.html', context=context)
    except TemplateNotFound:
        abort(404)


@app.route('/reset/', endpoint='reset_handler', methods=['GET'])
def reset_handler() -> Response:
    cache.clear()
    return redirect('/', code=302)


################################################################################
# End
################################################################################
# required host 0.0.0.0 for docker.
if __name__ == "__main__":
    app.run(host="0.0.0.0", debug=FLASK_DEBUG)
