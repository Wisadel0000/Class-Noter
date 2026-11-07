from wikiencoder import WikiStore
from wikiencoder.export import export_site

wiki_path = "../../note/raw"
out_path = "../../note/wiki"
site_name ="WIKI笔记库"

store = WikiStore(wiki_path,author="Nairy")

export_site(store,out_path,site_name=site_name)