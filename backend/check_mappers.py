from sqlalchemy.orm import configure_mappers

import app.models

configure_mappers()

print("SQLAlchemy mapper configuration succeeded.")