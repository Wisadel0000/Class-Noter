from wikiencoder import WikiStore
from wikiencoder.export import export_site

wiki_path = "wiki"
out_path = "out"
site_name ="Websocket!!"

store = WikiStore(wiki_path,author="Nairy")

export_site(store,out_path,site_name=site_name)