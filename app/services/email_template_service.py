from jinja2 import (
    Environment,
    FileSystemLoader,
)

env = Environment(
    loader=FileSystemLoader(
        "app/templates"
    )
)


def render_template(
    template_name: str,
    **context,
) -> str:
    template = env.get_template(
        template_name
    )

    return template.render(
        **context
    )