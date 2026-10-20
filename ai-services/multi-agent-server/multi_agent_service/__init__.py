"""TripGenie shared Multi-Agent Server (Release 2).

Planner, Worker and Reviewer agents run over the shared AI-Mode gateway, and
every run ends with a human decision. Feature backends call this service over
HTTP; it is a host process and never a Docker Compose service.
"""

__version__ = "0.1.0"
