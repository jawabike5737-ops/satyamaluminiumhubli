from .utils import get_ram_usage
import logging

def ram_usage(request):
    """Provide lightweight RAM usage info for templates.

    This context processor is deliberately conservative — it never raises.
    """
    logger = logging.getLogger(__name__)
    try:
        ram = get_ram_usage()
        return { 'ram': ram }
    except Exception as e:
        logger.exception('Failed to get RAM usage for context processor: %s', e)
        return { 'ram': None }
