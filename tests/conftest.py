import os

os.environ["SLM_BACKEND"] = "none"          # tests never download a model
os.environ["CONTACT_EMAIL"] = "tests@example.com"
