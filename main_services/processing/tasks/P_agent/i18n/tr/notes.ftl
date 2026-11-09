# Translation of en/notes.ftl. Change it together with the English catalog.

# The notes that the worker writes into a run, and the text of a turn that the worker ends.
# The model reads each note. The transcript shows the notes and the ending to the person.
# The worker reads plain text and { $name } variables only (`tasks.P_agent.notes`).

## Discovery

note-discovery-l4 = Şimdi isteği yanıtlayabilecek sonuç sayfalarını oku: en fazla 6 URL'sini tek bir read_page çağrısında, `urls` listesine koy. Tek çağrı hepsini aynı anda okur.

## Page captures


## Sources


## Named things


## Search progress

note-progress-level = Arama ilerleme düzeyi { $level }.
note-progress-searches = Şimdiye kadar yapılan aramalar:
note-progress-search = { $name } { $args }: { $items } öğe, { $matches } anahtar sözcük eşleşmesi.
note-progress-available = Hâlâ kullanılabilir arama adımları:
note-progress-complete = Kullanılabilir arama adımları tamamlandı.
note-progress-write-now = Şimdi yanıtı ya da raporu yaz. Okunan kaynakların neyi içermediğini belirt ve aramaları adlandır.
note-progress-answer-next = Sonraki yanıt, nihai yanıt olmalı. Eksik olguları ve yaptığın aramaları belirt.
note-progress-step-quoted = Her adı, search_collections ile tırnak içinde bir ifade olarak ara.
note-progress-step-variants = Tırnaksız sözcükleri ve ad varyantlarını ara. Sözcük sayılarını ve yazım adaylarını oku.
note-progress-step-filters = Filtreleri birer birer kaldır ve filtresiz bir arama yap.
note-progress-step-facets = Filtre değerlerini search_facet_values ile doğrula.
note-progress-step-dates = Tarihleri search_histogram ile doğrula.
note-progress-step-passages = Bir içerik tanımını search_passages ile ara.
note-progress-step-folder = İstenen klasör, yol ya da dosya için { $tool } kullan.
note-progress-step-read-hits = En iyi 1 ila 3 sonucu { $tool } ile oku.
note-progress-step-web-search = Web'de web_search ile ara ve en iyi sonuç sayfalarını oku.
note-progress-step-page-find = Uzun bir sayfanın saklanan metnini read_page ve find ile ara.
note-progress-step-page-retry = Başka bir sonuç adresini ya da başarısız olan sayfanın arşivlenmiş kopyasını oku.
note-progress-ended = Çalışma, ilerleme olmadan tekrarlanan aramalardan sonra bitti.
note-progress-ended-none = Anahtar sözcükle eşleşen kaynak bulunamadı.
note-progress-ended-some = Aramalar anahtar sözcükle eşleşen { $count } kaynak buldu. Ajan yanıtını tamamlamadı.
note-progress-ended-searches = Yapılan aramalar:
