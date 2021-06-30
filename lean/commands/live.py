# QUANTCONNECT.COM - Democratizing Finance, Empowering Individuals.
# Lean CLI v1.0. Copyright 2021 QuantConnect Corporation.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

import click

from lean.click import LeanCommand, PathParameter, ensure_options
from lean.constants import DEFAULT_ENGINE_IMAGE
from lean.container import container
from lean.models.brokerages.local import all_local_brokerages, local_brokerage_data_feeds, all_local_data_feeds
from lean.models.brokerages.local.binance import BinanceBrokerage, BinanceDataFeed
from lean.models.brokerages.local.bitfinex import BitfinexBrokerage, BitfinexDataFeed
from lean.models.brokerages.local.bloomberg import BloombergBrokerage, BloombergDataFeed
from lean.models.brokerages.local.coinbase_pro import CoinbaseProBrokerage, CoinbaseProDataFeed
from lean.models.brokerages.local.interactive_brokers import InteractiveBrokersBrokerage, InteractiveBrokersDataFeed
from lean.models.brokerages.local.iqfeed import IQFeedDataFeed
from lean.models.brokerages.local.oanda import OANDABrokerage, OANDADataFeed
from lean.models.brokerages.local.paper_trading import PaperTradingBrokerage
from lean.models.brokerages.local.tradier import TradierBrokerage, TradierDataFeed
from lean.models.brokerages.local.zerodha import ZerodhaBrokerage, ZerodhaDataFeed
from lean.models.errors import MoreInfoError
from lean.models.logger import Option

# Brokerage -> required configuration properties
_required_brokerage_properties = {
    "InteractiveBrokersBrokerage": ["ib-account", "ib-user-name", "ib-password",
                                    "ib-agent-description", "ib-trading-mode"],
    "TradierBrokerage": ["tradier-use-sandbox", "tradier-account-id", "tradier-access-token"],
    "OandaBrokerage": ["oanda-environment", "oanda-access-token", "oanda-account-id"],
    "GDAXBrokerage": ["gdax-api-secret", "gdax-api-key", "gdax-passphrase"],
    "BitfinexBrokerage": ["bitfinex-api-secret", "bitfinex-api-key"],
    "BinanceBrokerage": ["binance-api-secret", "binance-api-key"],
    "ZerodhaBrokerage": ["zerodha-access-token", "zerodha-api-key", "zerodha-product-type", "zerodha-trading-segment"],
    "BloombergBrokerage": ["job-organization-id", "bloomberg-api-type", "bloomberg-environment",
                           "bloomberg-server-host", "bloomberg-server-port", "bloomberg-emsx-broker"]
}

# Data queue handler -> required configuration properties
_required_data_queue_handler_properties = {
    "QuantConnect.Brokerages.InteractiveBrokers.InteractiveBrokersBrokerage":
        _required_brokerage_properties["InteractiveBrokersBrokerage"] + ["ib-enable-delayed-streaming-data"],
    "TradierBrokerage": _required_brokerage_properties["TradierBrokerage"],
    "OandaBrokerage": _required_brokerage_properties["OandaBrokerage"],
    "GDAXDataQueueHandler": _required_brokerage_properties["GDAXBrokerage"],
    "BitfinexBrokerage": _required_brokerage_properties["BitfinexBrokerage"],
    "BinanceBrokerage": _required_brokerage_properties["BinanceBrokerage"],
    "ZerodhaBrokerage": _required_brokerage_properties["ZerodhaBrokerage"] + ["zerodha-history-subscription"],
    "BloombergBrokerage": _required_brokerage_properties["BloombergBrokerage"],
    "QuantConnect.ToolBox.IQFeed.IQFeedDataQueueHandler": ["iqfeed-iqconnect", "iqfeed-productName", "iqfeed-version"]
}

_environment_skeleton = {
    "live-mode": True,
    "setup-handler": "QuantConnect.Lean.Engine.Setup.BrokerageSetupHandler",
    "result-handler": "QuantConnect.Lean.Engine.Results.LiveTradingResultHandler",
    "data-feed-handler": "QuantConnect.Lean.Engine.DataFeeds.LiveTradingDataFeed",
    "real-time-handler": "QuantConnect.Lean.Engine.RealTime.LiveTradingRealTimeHandler"
}


def _raise_for_missing_properties(lean_config: Dict[str, Any], environment_name: str, lean_config_path: Path) -> None:
    """Raises an error if any required properties are missing.

    :param lean_config: the LEAN configuration that should be used
    :param environment_name: the name of the environment
    :param lean_config_path: the path to the LEAN configuration file
    """
    environment = lean_config["environments"][environment_name]
    for key in ["live-mode-brokerage", "data-queue-handler"]:
        if key not in environment:
            raise MoreInfoError(f"The '{environment_name}' environment does not specify a {key}",
                                "https://www.lean.io/docs/lean-cli/tutorials/live-trading/local-live-trading")

    brokerage = environment["live-mode-brokerage"]
    data_queue_handler = environment["data-queue-handler"]

    brokerage_properties = _required_brokerage_properties.get(brokerage, [])
    data_queue_handler_properties = _required_data_queue_handler_properties.get(data_queue_handler, [])

    required_properties = brokerage_properties + data_queue_handler_properties
    missing_properties = [p for p in required_properties if p not in lean_config or lean_config[p] == ""]
    missing_properties = set(missing_properties)
    if len(missing_properties) == 0:
        return

    properties_str = "properties" if len(missing_properties) > 1 else "property"
    these_str = "these" if len(missing_properties) > 1 else "this"

    missing_properties = "\n".join(f"- {p}" for p in missing_properties)

    raise RuntimeError(f"""
Please configure the following missing {properties_str} in {lean_config_path}:
{missing_properties}
Go to the following url for documentation on {these_str} {properties_str}:
https://www.lean.io/docs/lean-cli/tutorials/live-trading/local-live-trading
    """.strip())


def _start_iqconnect_if_necessary(lean_config: Dict[str, Any], environment_name: str) -> None:
    """Starts IQConnect if the given environment uses IQFeed as data queue handler.

    :param lean_config: the LEAN configuration that should be used
    :param environment_name: the name of the environment
    """
    environment = lean_config["environments"][environment_name]
    if environment["data-queue-handler"] != "QuantConnect.ToolBox.IQFeed.IQFeedDataQueueHandler":
        return

    args = [lean_config["iqfeed-iqconnect"],
            "-product", lean_config["iqfeed-productName"],
            "-version", lean_config["iqfeed-version"]]

    username = lean_config.get("iqfeed-username", "")
    if username != "":
        args.extend(["-login", username])

    password = lean_config.get("iqfeed-password", "")
    if password != "":
        args.extend(["-password", password])

    subprocess.Popen(args)

    container.logger().info("Waiting 10 seconds for IQFeed to start")
    time.sleep(10)


def _configure_lean_config_interactively(lean_config: Dict[str, Any], environment_name: str) -> None:
    """Interactively configures the Lean config to use.

    Asks the user all questions required to set up the Lean config for local live trading.

    :param lean_config: the base lean config to use
    :param environment_name: the name of the environment to configure
    """
    logger = container.logger()

    lean_config["environments"] = {
        environment_name: _environment_skeleton
    }

    brokerage = logger.prompt_list("Select a brokerage", [
        Option(id=brokerage, label=brokerage.get_name()) for brokerage in all_local_brokerages
    ])

    brokerage.build(lean_config, logger).configure(lean_config, environment_name)

    data_feed = logger.prompt_list("Select a data feed", [
        Option(id=data_feed, label=data_feed.get_name()) for data_feed in local_brokerage_data_feeds[brokerage]
    ])

    data_feed.build(lean_config, logger).configure(lean_config, environment_name)


_cached_organizations = None


def _get_organization_id(given_input: str) -> str:
    """Converts the organization name or id given by the user to an organization id.

    Raises an error if the user is not a member of an organization with the given name or id.

    :param given_input: the input given by the user
    :return: the id of the organization given by the user
    """
    global _cached_organizations
    if _cached_organizations is None:
        api_client = container.api_client()
        _cached_organizations = api_client.organizations.get_all()

    organization = next((o for o in _cached_organizations if o.id == given_input or o.name == given_input), None)
    if organization is None:
        raise RuntimeError(f"You are not a member of an organization with name or id '{given_input}'")

    return organization.id


_cached_lean_config = None


def _get_default_value(key: str) -> Optional[Any]:
    """Returns the default value for an option based on the Lean config.

    :param key: the name of the property in the Lean config that supplies the default value of an option
    :return: the value of the property in the Lean config, or None if there is none
    """
    global _cached_lean_config
    if _cached_lean_config is None:
        _cached_lean_config = container.lean_config_manager().get_lean_config()

    if key not in _cached_lean_config:
        return None

    value = _cached_lean_config[key]
    if value == "":
        return None

    if key == "iqfeed-iqconnect" and not Path(value).is_file():
        return None

    return value


@click.command(cls=LeanCommand, requires_lean_config=True, requires_docker=True)
@click.argument("project", type=PathParameter(exists=True, file_okay=True, dir_okay=True))
@click.option("--environment",
              type=str,
              help="The environment to use")
@click.option("--output",
              type=PathParameter(exists=False, file_okay=False, dir_okay=True),
              help="Directory to store results in (defaults to PROJECT/live/TIMESTAMP)")
@click.option("--brokerage",
              type=click.Choice([b.get_name() for b in all_local_brokerages], case_sensitive=False),
              help="The brokerage to use")
@click.option("--data-feed",
              type=click.Choice([d.get_name() for d in all_local_data_feeds], case_sensitive=False),
              help="The data feed to use")
@click.option("--ib-user-name",
              type=str,
              default=lambda: _get_default_value("ib-user-name"),
              help="Your Interactive Brokers username")
@click.option("--ib-account",
              type=str,
              default=lambda: _get_default_value("ib-account"),
              help="Your Interactive Brokers account id")
@click.option("--ib-password",
              type=str,
              default=lambda: _get_default_value("ib-password"),
              help="Your Interactive Brokers password")
@click.option("--ib-enable-delayed-streaming-data",
              type=bool,
              default=lambda: _get_default_value("ib-enable-delayed-streaming-data"),
              help="Whether delayed data may be used when your algorithm subscribes to a security you don't have a market data subscription for")
@click.option("--tradier-account-id",
              type=str,
              default=lambda: _get_default_value("tradier-account-id"),
              help="Your Tradier account id")
@click.option("--tradier-access-token",
              type=str,
              default=lambda: _get_default_value("tradier-access-token"),
              help="Your Tradier access token")
@click.option("--tradier-use-sandbox",
              type=bool,
              default=lambda: _get_default_value("tradier-use-sandbox"),
              help="Whether the developer sandbox should be used")
@click.option("--oanda-account-id",
              type=str,
              default=lambda: _get_default_value("oanda-account-id"),
              help="Your OANDA account id")
@click.option("--oanda-access-token",
              type=str,
              default=lambda: _get_default_value("oanda-access-token"),
              help="Your OANDA API token")
@click.option("--oanda-environment",
              type=click.Choice(["Practice", "Trade"], case_sensitive=False),
              default=lambda: _get_default_value("oanda-environment"),
              help="The environment to run in, Practice for fxTrade Practice, Trade for fxTrade")
@click.option("--bitfinex-api-key",
              type=str,
              default=lambda: _get_default_value("bitfinex-api-key"),
              help="Your Bitfinex API key")
@click.option("--bitfinex-api-secret",
              type=str,
              default=lambda: _get_default_value("bitfinex-api-secret"),
              help="Your Bitfinex API secret")
@click.option("--gdax-api-key",
              type=str,
              default=lambda: _get_default_value("gdax-api-key"),
              help="Your Coinbase Pro API key")
@click.option("--gdax-api-secret",
              type=str,
              default=lambda: _get_default_value("gdax-api-secret"),
              help="Your Coinbase Pro API secret")
@click.option("--gdax-passphrase",
              type=str,
              default=lambda: _get_default_value("gdax-passphrase"),
              help="Your Coinbase Pro API passphrase")
@click.option("--binance-api-key",
              type=str,
              default=lambda: _get_default_value("binance-api-key"),
              help="Your Binance API key")
@click.option("--binance-api-secret",
              type=str,
              default=lambda: _get_default_value("binance-api-secret"),
              help="Your Binance API secret")
@click.option("--zerodha-api-key",
              type=str,
              default=lambda: _get_default_value("zerodha-api-key"),
              help="Your Kite Connect API key")
@click.option("--zerodha-access-token",
              type=str,
              default=lambda: _get_default_value("zerodha-access-token"),
              help="Your Kite Connect access token")
@click.option("--zerodha-product-type",
              type=click.Choice(["MIS", "CNC", "NRML"], case_sensitive=False),
              default=lambda: _get_default_value("zerodha-product-type"),
              help="MIS if you are targeting intraday products, CNC if you are targeting delivery products, NRML if you are targeting carry forward products")
@click.option("--zerodha-trading-segment",
              type=click.Choice(["EQUITY", "COMMODITY"], case_sensitive=False),
              default=lambda: _get_default_value("zerodha-trading-segment"),
              help="EQUITY if you are trading equities on NSE or BSE, COMMODITY if you are trading commodities on MCX")
@click.option("--zerodha-history-subscription",
              type=bool,
              default=lambda: _get_default_value("zerodha-history-subscription"),
              help="Whether you have a history API subscription for Zerodha")
@click.option("--iqfeed-iqconnect",
              type=PathParameter(exists=True, file_okay=True, dir_okay=False),
              default=lambda: _get_default_value("iqfeed-iqconnect"),
              help="The path to the IQConnect binary")
@click.option("--iqfeed-username",
              type=str,
              default=lambda: _get_default_value("iqfeed-username"),
              help="Your IQFeed username")
@click.option("--iqfeed-password",
              type=str,
              default=lambda: _get_default_value("iqfeed-password"),
              help="Your IQFeed password")
@click.option("--iqfeed-product-name",
              type=str,
              default=lambda: _get_default_value("iqfeed-productName"),
              help="The product name of your IQFeed developer account")
@click.option("--iqfeed-version",
              type=str,
              default=lambda: _get_default_value("iqfeed-version"),
              help="The product version of your IQFeed developer account")
@click.option("--bloomberg-organization",
              type=str,
              default=lambda: _get_default_value("job-organization-id"),
              help="The name or id of the organization with the Bloomberg module subscription")
@click.option("--bloomberg-environment",
              type=click.Choice(["Production", "Beta"], case_sensitive=False),
              default=lambda: _get_default_value("bloomberg-environment"),
              help="The environment to run in")
@click.option("--bloomberg-server-host",
              type=str,
              default=lambda: _get_default_value("bloomberg-server-host"),
              help="The host of the Bloomberg server")
@click.option("--bloomberg-server-port",
              type=int,
              default=lambda: _get_default_value("bloomberg-server-port"),
              help="The port of the Bloomberg server")
@click.option("--bloomberg-symbol-map-file",
              type=PathParameter(exists=True, file_okay=True, dir_okay=False),
              default=lambda: _get_default_value("bloomberg-symbol-map-file"),
              help="The path to the Bloomberg symbol map file")
@click.option("--bloomberg-emsx-broker",
              type=str,
              default=lambda: _get_default_value("bloomberg-emsx-broker"),
              help="The EMSX broker to use")
@click.option("--bloomberg-emsx-user-time-zone",
              type=str,
              default=lambda: _get_default_value("bloomberg-emsx-user-time-zone"),
              help="The EMSX user timezone to use")
@click.option("--bloomberg-emsx-account",
              type=str,
              default=lambda: _get_default_value("bloomberg-emsx-account"),
              help="The EMSX account to use")
@click.option("--bloomberg-emsx-strategy",
              type=str,
              default=lambda: _get_default_value("bloomberg-emsx-strategy"),
              help="The EMSX strategy to use")
@click.option("--bloomberg-emsx-notes",
              type=str,
              default=lambda: _get_default_value("bloomberg-emsx-notes"),
              help="The EMSX notes to use")
@click.option("--bloomberg-emsx-handling",
              type=str,
              default=lambda: _get_default_value("bloomberg-emsx-handling"),
              help="The EMSX handling to use")
@click.option("--bloomberg-execution",
              type=str,
              default=lambda: _get_default_value("bloomberg-execution"),
              help="Bloomberg execution")
@click.option("--bloomberg-allow-modification",
              type=bool,
              default=lambda: _get_default_value("bloomberg-allow-modification"),
              help="Whether modification is allowed")
@click.option("--image",
              type=str,
              help=f"The LEAN engine image to use (defaults to {DEFAULT_ENGINE_IMAGE})")
@click.option("--update",
              is_flag=True,
              default=False,
              help="Pull the LEAN engine image before starting live trading")
@click.pass_context
def live(ctx: click.Context,
         project: Path,
         environment: Optional[str],
         output: Optional[Path],
         brokerage: Optional[str],
         data_feed: Optional[str],
         ib_user_name: Optional[str],
         ib_account: Optional[str],
         ib_password: Optional[str],
         ib_enable_delayed_streaming_data: Optional[bool],
         tradier_account_id: Optional[str],
         tradier_access_token: Optional[str],
         tradier_use_sandbox: Optional[bool],
         oanda_account_id: Optional[str],
         oanda_access_token: Optional[str],
         oanda_environment: Optional[str],
         bitfinex_api_key: Optional[str],
         bitfinex_api_secret: Optional[str],
         gdax_api_key: Optional[str],
         gdax_api_secret: Optional[str],
         gdax_passphrase: Optional[str],
         binance_api_key: Optional[str],
         binance_api_secret: Optional[str],
         zerodha_api_key: Optional[str],
         zerodha_access_token: Optional[str],
         zerodha_product_type: Optional[str],
         zerodha_trading_segment: Optional[str],
         zerodha_history_subscription: Optional[bool],
         iqfeed_iqconnect: Optional[Path],
         iqfeed_username: Optional[str],
         iqfeed_password: Optional[str],
         iqfeed_product_name: Optional[str],
         iqfeed_version: Optional[str],
         bloomberg_organization: Optional[str],
         bloomberg_environment: Optional[str],
         bloomberg_server_host: Optional[str],
         bloomberg_server_port: Optional[int],
         bloomberg_symbol_map_file: Optional[Path],
         bloomberg_emsx_broker: Optional[str],
         bloomberg_emsx_user_time_zone: Optional[str],
         bloomberg_emsx_account: Optional[str],
         bloomberg_emsx_strategy: Optional[str],
         bloomberg_emsx_notes: Optional[str],
         bloomberg_emsx_handling: Optional[str],
         bloomberg_execution: Optional[bool],
         bloomberg_allow_modification: Optional[bool],
         image: Optional[str],
         update: bool) -> None:
    """Start live trading a project locally using Docker.

    \b
    If PROJECT is a directory, the algorithm in the main.py or Main.cs file inside it will be executed.
    If PROJECT is a file, the algorithm in the specified file will be executed.

    By default an interactive wizard is shown letting you configure the brokerage and data feed to use.
    If --environment, --brokerage or --data-feed are given the command runs in non-interactive mode.
    In this mode the CLI does not prompt for input.

    If --environment is given it must be the name of a live environment in the Lean configuration.

    If --brokerage and --data-feed are given, the options specific to the given brokerage/data feed must also be given.
    The Lean config is used as fallback when a brokerage/data feed-specific option hasn't been passed in.
    If a required option is not given and cannot be found in the Lean config the command aborts.

    By default the official LEAN engine image is used.
    You can override this using the --image option.
    Alternatively you can set the default engine image for all commands using `lean config set engine-image <image>`.
    """
    # Reset globals so we reload everything in between tests
    global _cached_organizations
    _cached_organizations = None
    global _cached_lean_config
    _cached_lean_config = None

    project_manager = container.project_manager()
    algorithm_file = project_manager.find_algorithm_file(Path(project))

    if output is None:
        output = algorithm_file.parent / "live" / datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

    lean_config_manager = container.lean_config_manager()

    if environment is not None:
        environment_name = environment
        lean_config = lean_config_manager.get_complete_lean_config(environment_name, algorithm_file, None)
    elif brokerage is not None or data_feed is not None:
        ensure_options(ctx, ["brokerage", "data_feed"])

        brokerage_configurer = None
        data_feed_configurer = None

        if brokerage == PaperTradingBrokerage.get_name():
            brokerage_configurer = PaperTradingBrokerage()
        elif brokerage == InteractiveBrokersBrokerage.get_name():
            ensure_options(ctx, ["ib_user_name", "ib_account", "ib_password"])
            brokerage_configurer = InteractiveBrokersBrokerage(ib_user_name, ib_account, ib_password)
        elif brokerage == TradierBrokerage.get_name():
            ensure_options(ctx, ["tradier_account_id", "tradier_access_token", "tradier_use_sandbox"])
            brokerage_configurer = TradierBrokerage(tradier_account_id, tradier_access_token, tradier_use_sandbox)
        elif brokerage == OANDABrokerage.get_name():
            ensure_options(ctx, ["oanda_account_id", "oanda_access_token", "oanda_environment"])
            brokerage_configurer = OANDABrokerage(oanda_account_id, oanda_access_token, oanda_environment)
        elif brokerage == BitfinexBrokerage.get_name():
            ensure_options(ctx, ["bitfinex_api_key", "bitfinex_api_secret"])
            brokerage_configurer = BitfinexBrokerage(bitfinex_api_key, bitfinex_api_secret)
        elif brokerage == CoinbaseProBrokerage.get_name():
            ensure_options(ctx, ["gdax_api_key", "gdax_api_secret", "gdax_passphrase"])
            brokerage_configurer = CoinbaseProBrokerage(gdax_api_key, gdax_api_secret, gdax_passphrase)
        elif brokerage == BinanceBrokerage.get_name():
            ensure_options(ctx, ["binance_api_key", "binance_api_secret"])
            brokerage_configurer = BinanceBrokerage(binance_api_key, binance_api_secret)
        elif brokerage == ZerodhaBrokerage.get_name():
            ensure_options(ctx, ["zerodha_api_key",
                                 "zerodha_access_token",
                                 "zerodha_product_type",
                                 "zerodha_trading_segment"])
            brokerage_configurer = ZerodhaBrokerage(zerodha_api_key,
                                                    zerodha_access_token,
                                                    zerodha_product_type,
                                                    zerodha_trading_segment)
        elif brokerage == BloombergBrokerage.get_name():
            ensure_options(ctx, ["bloomberg_organization",
                                 "bloomberg_environment",
                                 "bloomberg_server_host",
                                 "bloomberg_server_port",
                                 "bloomberg_emsx_broker",
                                 "bloomberg_execution",
                                 "bloomberg_allow_modification"])
            brokerage_configurer = BloombergBrokerage(_get_organization_id(bloomberg_organization),
                                                      bloomberg_environment,
                                                      bloomberg_server_host,
                                                      bloomberg_server_port,
                                                      bloomberg_symbol_map_file,
                                                      bloomberg_emsx_broker,
                                                      bloomberg_emsx_user_time_zone,
                                                      bloomberg_emsx_account,
                                                      bloomberg_emsx_strategy,
                                                      bloomberg_emsx_notes,
                                                      bloomberg_emsx_handling,
                                                      bloomberg_execution,
                                                      bloomberg_allow_modification)

        if data_feed == InteractiveBrokersDataFeed.get_name():
            ensure_options(ctx, ["ib_user_name", "ib_account", "ib_password", "ib_enable_delayed_streaming_data"])
            data_feed_configurer = InteractiveBrokersDataFeed(InteractiveBrokersBrokerage(ib_user_name,
                                                                                          ib_account,
                                                                                          ib_password),
                                                              ib_enable_delayed_streaming_data)
        elif data_feed == TradierDataFeed.get_name():
            ensure_options(ctx, ["tradier_account_id", "tradier_access_token", "tradier_use_sandbox"])
            data_feed_configurer = TradierDataFeed(TradierBrokerage(tradier_account_id,
                                                                    tradier_access_token,
                                                                    tradier_use_sandbox))
        elif data_feed == OANDADataFeed.get_name():
            ensure_options(ctx, ["oanda_account_id", "oanda_access_token", "oanda_environment"])
            data_feed_configurer = OANDADataFeed(OANDABrokerage(oanda_account_id,
                                                                oanda_access_token,
                                                                oanda_environment))
        elif data_feed == BitfinexDataFeed.get_name():
            ensure_options(ctx, ["bitfinex_api_key", "bitfinex_api_secret"])
            data_feed_configurer = BitfinexDataFeed(BitfinexBrokerage(bitfinex_api_key, bitfinex_api_secret))
        elif data_feed == CoinbaseProDataFeed.get_name():
            ensure_options(ctx, ["gdax_api_key", "gdax_api_secret", "gdax_passphrase"])
            data_feed_configurer = CoinbaseProDataFeed(CoinbaseProBrokerage(gdax_api_key,
                                                                            gdax_api_secret,
                                                                            gdax_passphrase))
        elif data_feed == BinanceDataFeed.get_name():
            ensure_options(ctx, ["binance_api_key", "binance_api_secret"])
            data_feed_configurer = BinanceDataFeed(BinanceBrokerage(binance_api_key, binance_api_secret))
        elif data_feed == ZerodhaDataFeed.get_name():
            ensure_options(ctx, ["zerodha_api_key",
                                 "zerodha_access_token",
                                 "zerodha_product_type",
                                 "zerodha_trading_segment",
                                 "zerodha_history_subscription"])
            data_feed_configurer = ZerodhaDataFeed(ZerodhaBrokerage(zerodha_api_key,
                                                                    zerodha_access_token,
                                                                    zerodha_product_type,
                                                                    zerodha_trading_segment),
                                                   zerodha_history_subscription)
        elif data_feed == BloombergDataFeed.get_name():
            ensure_options(ctx, ["bloomberg_organization",
                                 "bloomberg_environment",
                                 "bloomberg_server_host",
                                 "bloomberg_server_port",
                                 "bloomberg_emsx_broker",
                                 "bloomberg_execution",
                                 "bloomberg_allow_modification"])
            data_feed_configurer = BloombergDataFeed(BloombergBrokerage(_get_organization_id(bloomberg_organization),
                                                                        bloomberg_environment,
                                                                        bloomberg_server_host,
                                                                        bloomberg_server_port,
                                                                        bloomberg_symbol_map_file,
                                                                        bloomberg_emsx_broker,
                                                                        bloomberg_emsx_user_time_zone,
                                                                        bloomberg_emsx_account,
                                                                        bloomberg_emsx_strategy,
                                                                        bloomberg_emsx_notes,
                                                                        bloomberg_emsx_handling,
                                                                        bloomberg_execution,
                                                                        bloomberg_allow_modification))
        elif data_feed == IQFeedDataFeed.get_name():
            ensure_options(ctx, ["iqfeed_iqconnect",
                                 "iqfeed_username",
                                 "iqfeed_password",
                                 "iqfeed_product_name",
                                 "iqfeed_version"])
            data_feed_configurer = IQFeedDataFeed(iqfeed_iqconnect,
                                                  iqfeed_username,
                                                  iqfeed_password,
                                                  iqfeed_product_name,
                                                  iqfeed_version)

        environment_name = "lean-cli"
        lean_config = lean_config_manager.get_complete_lean_config(environment_name, algorithm_file, None)

        lean_config["environments"] = {
            environment_name: _environment_skeleton
        }

        brokerage_configurer.configure(lean_config, environment_name)
        data_feed_configurer.configure(lean_config, environment_name)
    else:
        environment_name = "lean-cli"
        lean_config = lean_config_manager.get_complete_lean_config(environment_name, algorithm_file, None)
        _configure_lean_config_interactively(lean_config, environment_name)

    if "environments" not in lean_config or environment_name not in lean_config["environments"]:
        lean_config_path = lean_config_manager.get_lean_config_path()
        raise MoreInfoError(f"{lean_config_path} does not contain an environment named '{environment_name}'",
                            "https://www.lean.io/docs/lean-cli/tutorials/live-trading/local-live-trading")

    if not lean_config["environments"][environment_name]["live-mode"]:
        raise MoreInfoError(f"The '{environment_name}' is not a live trading environment (live-mode is set to false)",
                            "https://www.lean.io/docs/lean-cli/tutorials/live-trading/local-live-trading")

    _raise_for_missing_properties(lean_config, environment_name, lean_config_manager.get_lean_config_path())

    cli_config_manager = container.cli_config_manager()
    engine_image = cli_config_manager.get_engine_image(image)

    docker_manager = container.docker_manager()

    if update or not docker_manager.supports_dotnet_5(engine_image) or not docker_manager.image_installed(engine_image):
        docker_manager.pull_image(engine_image)

    _start_iqconnect_if_necessary(lean_config, environment_name)

    lean_runner = container.lean_runner()
    lean_runner.run_lean(lean_config, environment_name, algorithm_file, output, engine_image, None)

    if str(engine_image) == DEFAULT_ENGINE_IMAGE and not update:
        update_manager = container.update_manager()
        update_manager.warn_if_docker_image_outdated(engine_image)
