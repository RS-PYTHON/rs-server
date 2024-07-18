"""Dummy module."""
class HelloWorld:
    """Dummy processor."""
    def __init__(self, parameters, **kwargs):
        """Dummy method."""

    def execute(self):
        """Dummy method."""
        return {"message": "Hello, world"}

    def __repr__(self):
        """Dummy method."""
        return '<HelloWorld>'

processors = {
    'HelloWorld': HelloWorld
}
