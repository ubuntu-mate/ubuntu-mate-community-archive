
# Ubuntu MATE Community Archive

A static archive of the Ubuntu MATE Discourse instance that ran from
January 2015 to April 2026.

The archive can be accessed at <https://ubuntu-mate.community>.


## Building

To set up a virtual environment:

    python -m venv venv
    source venv/bin/activate
    pip install jinja2

Then run:

    python scripts/05_export_html.py

Routes and redirects are handled by Cloudflare R2 workers.


## License

Posts and user contributions were licensed under [CC BY-NC-SA 3.0](https://creativecommons.org/licenses/by-nc-sa/3.0/deed.en).

The scripts in this repository are licensed under GPLv3.
