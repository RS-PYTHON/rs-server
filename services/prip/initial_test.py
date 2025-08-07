
import eodag
import os

os.environ["EODAG_EXT_PRODUCT_TYPES_CFG_FILE"] = ""
dag = eodag.EODataAccessGateway(user_conf_file_path='config/prip_ws_config.yaml')

x = dag.search(productType="cams-ads-grf-aux",
               provider="prip",
               PublicationDate = "2022-06-26T06:30:34.558Z",
               raise_errors=True)

print(x)

print("*")