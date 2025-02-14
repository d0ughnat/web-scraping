import flask

app = flask.Flask(__name__, template_folder="/home/natty/web-scraping/template")

@app.route("/")
def index():
  return flask.render_template("index.html")


if __name__ == "__main__":
  app.run()

