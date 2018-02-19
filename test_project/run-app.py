import os
import testing.postgresql

project_name = "test_project"
db_dir = "{}_db".format(project_name)
db_port = 54323

make_db = True
try:
    os.mkdir(db_dir)
except OSError:
    make_db = False

# Launch new PostgreSQL server
print("Setting up postgres DB...")
with testing.postgresql.Postgresql(name=project_name, port=db_port, base_dir=db_dir) as postgresql:
    # connect to PostgreSQL
    print(postgresql.url(), db_dir)
    if make_db:
        # Enable plugin for uuid generation
        os.system("""psql -d {} -c 'CREATE EXTENSION IF NOT EXISTS "uuid-ossp";'""".format(postgresql.url()))
        print("Initializing db")
        os.system("bin/python bin/initialize_{0}_db {0}/development.ini".format(project_name))
    else:
        print("Re-using existing DB.")
    print("Starting gunicorn")
    os.system("bin/python bin/gunicorn --reload --paste {}/development.ini --capture-output".format(project_name))
