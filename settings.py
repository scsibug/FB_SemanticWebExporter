from gluon.storage import Storage
facebook_settings=Storage()
facebook_settings.FACEBOOK_API_KEY = 'xxx'
facebook_settings.FACEBOOK_SECRET_KEY = 'xxx'
facebook_settings.FACEBOOK_APP_NAME = "Semantic Web Exporter"
facebook_settings.FACEBOOK_INTERNAL = True
facebook_settings.FACEBOOK_CALLBACK_PATH = "/sw_exporter/main?"
