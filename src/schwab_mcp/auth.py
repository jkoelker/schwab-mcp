#
# Wrappers around schwab.auth to inject our own token manager
#

import logging

from schwab import auth

from schwab_mcp import tokens


client_from_access_functions = auth.client_from_access_functions


def easy_client(
    client_id: str,
    client_secret: str,
    callback_url: str,
    token_manager: tokens.Manager,
    asyncio: bool = False,
    enforce_enums: bool = True,
    max_token_age: int = 60 * 60 * 24 * 6.5,
    callback_timeout: float = 300.0,
    interactive: bool = True,
    requested_browser: str | None = None,
):
    if max_token_age is None:
        max_token_age = 0

    if max_token_age < 0:
        raise ValueError("max_token_age must be positive, zero, or None")

    logger = logging.getLogger(__name__)

    client = None

    if token_manager.exists():
        client = auth.client_from_access_functions(
            client_id,
            client_secret,
            token_manager.load,
            token_manager.write,
            asyncio=asyncio,
            enforce_enums=enforce_enums,
        )
        logger.info(f"Loaded token from {token_manager.path}")

        if max_token_age > 0 and client.token_age() >= max_token_age:
            logger.info("token too old, proactively creating a new one")
            client = None

    # Return early on success
    if client is not None:
        return client

    client
    client = client_from_login_flow(
        client_id,
        client_secret,
        callback_url,
        token_manager,
        asyncio=asyncio,
        enforce_enums=enforce_enums,
        callback_timeout=callback_timeout,
        requested_browser=requested_browser,
        interactive=interactive,
    )

    logger.info(
        f"Returning client fetched using web browser, writing token to '{token_manager.path}'"
    )

    return client


def client_from_login_flow(
    client_id: str,
    client_secret: str,
    callback_url: str,
    token_manager: tokens.Manager,
    asyncio: bool = False,
    enforce_enums: bool = True,
    callback_timeout: float = 300.0,
    interactive: bool = True,
    requested_browser: str | None = None,
):
    if callback_timeout is None:
        callback_timeout = 0

    if callback_timeout < 0:
        raise ValueError("callback_timeout must be positive")

    # Start the server
    parsed = auth.urllib.parse.urlparse(callback_url)

    if parsed.hostname != "127.0.0.1":
        # TODO: document this error
        raise ValueError(
            (
                "Disallowed hostname {}. client_from_login_flow only allows "
                + "callback URLs with hostname 127.0.0.1. See here for "
                + "more information: https://schwab-py.readthedocs.io/en/"
                + "latest/auth.html#callback-url-advisory"
            ).format(parsed.hostname)
        )

    callback_port = parsed.port if parsed.port else 443
    callback_path = parsed.path if parsed.path else "/"

    output_queue = auth.multiprocess.Queue()

    server = auth.multiprocess.Process(
        target=auth.__run_client_from_login_flow_server,
        args=(output_queue, callback_port, callback_path),
    )

    # Context manager to kill the server upon completion
    @auth.contextlib.contextmanager
    def callback_server():
        server.start()

        try:
            yield
        finally:
            try:
                auth.psutil.Process(server.pid).kill()
            except auth.psutil.NoSuchProcess:
                pass

    with callback_server():
        # Wait until the server successfully starts
        while True:
            # Check if the server is still alive
            if server.exitcode is not None:
                # TODO: document this error
                raise auth.RedirectServerExitedError(
                    "Redirect server exited. Are you attempting to use a "
                    + "callback URL without a port number specified?"
                )

            # Attempt to send a request to the server
            try:
                with auth.warnings.catch_warnings():
                    auth.warnings.filterwarnings(
                        "ignore",
                        category=auth.urllib3.exceptions.InsecureRequestWarning,
                    )

                    auth.httpx.get(
                        f"{callback_url}/schwab-py-internal/status",
                        verify=False,
                    )
                break
            except auth.httpx.ConnectError:
                pass

            auth.time.sleep(0.1)

        # Open the browser
        auth_context = auth.get_auth_context(client_id, callback_url)

        if interactive:
            print()
            print(
                "***********************************************************************"
            )
            print()
            print("This is the browser-assisted login and token creation flow for")
            print("schwab-py. This flow automatically opens the login page on your")
            print("browser, captures the resulting OAuth callback, and creates a token")
            print("using the result. The authorization URL is:")
            print()
            print(">>", auth_context.authorization_url)
            print()
            print("IMPORTANT: Your browser will give you a security warning about an")
            print("invalid certificate prior to issuing the redirect. This is because")
            print("schwab-py has started a server on your machine to receive the OAuth")
            print("redirect using a self-signed SSL certificate. You can ignore that")
            print("warning, but make sure to first check that the URL matches your")
            print(
                "callback URL, ignoring URL parameters. As a reminder, your callback URL"
            )
            print("is:")
            print()
            print(">>", callback_url)
            print()
            print("See here to learn more about self-signed SSL certificates:")
            print("https://schwab-py.readthedocs.io/en/latest/auth.html#ssl-errors")
            print()
            print("If you encounter any issues, see here for troubleshooting:")
            print(
                "https://schwab-py.readthedocs.io/en/latest/auth.html#troubleshooting"
            )
            print(
                "***********************************************************************"
            )
            print()

            input(
                "Press ENTER to open the browser. Note you can call "
                + "this method with interactive=False to skip this input."
            )

        controller = auth.webbrowser.get(requested_browser)
        controller.open(auth_context.authorization_url)

        # Wait for a response
        now = auth.__TIME_TIME()
        timeout_time = now + callback_timeout
        received_url = None
        while True:
            now = auth.__TIME_TIME()
            if now >= timeout_time:
                if callback_timeout == 0:
                    # XXX: We're detecting a test environment here to avoid an
                    #      infinite sleep. Surely there must be a better way to do
                    #      this...
                    if auth.__TIME_TIME != auth.time.time:  # pragma: no cover
                        raise ValueError("endless wait requested")
                else:
                    break

            # Attempt to fetch from the queue
            try:
                received_url = output_queue.get(timeout=min(timeout_time - now, 0.1))
                break
            except auth.queue.Empty:
                pass

        if not received_url:
            raise auth.RedirectTimeoutError(
                "Timed out waiting for a post-authorization callback. You "
                + "can set a longer timeout by passing a value of "
                + "callback_timeout to client_from_login_flow."
            )

        return auth.client_from_received_url(
            client_id,
            client_secret,
            auth_context,
            received_url,
            token_manager.write,
            asyncio=asyncio,
            enforce_enums=enforce_enums,
        )
