# Translation of en/notes.ftl. Change it together with the English catalog.

# The notes that the worker writes into a run, and the text of a turn that the worker ends.
# The model reads each note. The transcript shows the notes and the ending to the person.
# The worker reads plain text and { $name } variables only (`tasks.P_agent.notes`).

## Discovery

note-discovery-l2 = Son iki arama yeni bir kaynak bulmadı. Şimdi en iyi sonuç sayfalarını oku: en fazla 6 URL'sini tek bir read_page çağrısında, `urls` listesine koy. Yeniden aramayı yalnızca farklı bir soruyla yap.
note-discovery-l3-web = Hiçbir kaynak sayfasını okumadan yanıt verdin. Maddelerini destekleyen sayfaların URL'leriyle read_page'i bir kez çağır, `urls` listesinde en fazla 6 URL olsun. Sonra yanıtı, onu destekleyen kaynaklarla yeniden yaz.
note-discovery-l3-documents = Hiçbir belgeyi okumadan yanıt verdin. Maddelerini destekleyen belgeleri read_documents ile oku, tek çağrıda birkaç dosya karması kullan. Sonra yanıtı, onu destekleyen kaynaklarla yeniden yaz.
note-discovery-l4 = Şimdi isteği yanıtlayabilecek sonuç sayfalarını oku: en fazla 6 URL'sini tek bir read_page çağrısında, `urls` listesine koy. Tek çağrı hepsini aynı anda okur.

## Page captures

note-capture-empty = { $urls } yakalaması makale metni içermiyor. Başka bir kaynak oku. Bu sayfaya atıf yapma.

## Sources

note-web-tools-absent = Bu turda web araçları yok, bu yüzden herkese açık web sayfalarını okuyamazsın. Seçilen koleksiyonları kullan ve isteğin hangi kısmını yanıtlamadıklarını belirt.
note-sources-documents = Önce izin verilen belge koleksiyonlarında ara. İlgili belgelerini oku.
note-sources-documents-before-web = Önce izin verilen belge koleksiyonlarında ara. İlgili belgelerini oku. Web'i kullanmadan önce bu belgeleri oku.

## Named things

note-absent-collection = İzin verilen hiçbir koleksiyonun adı { $name } değil. İzin verilen koleksiyonlar: { $collections }.
note-absent-name = Seçilen koleksiyonlarda { $name } için dizinlenmiş bir eşleşme yok.
note-absent-close-forms = Dizinlenmiş yakın biçimler: { $forms }. Yakın bir biçimi istenen ad olarak kullanma. Birini aradığında, yanıtta bunu farklı bir yazım olarak belirt.
note-absent-close-form = { $form } ({ $count } belge)
note-absent-web = Bu turun web araçları adı arayabilir.

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
note-advice-stuck = Bir sohbet denetimi, son aramaların sonuçlarını yinelediğini tahmin ediyor. no_results becerisi bir aramanın diğer biçimlerini açıklar.
note-advice-absent = Bir sohbet denetimi, sonuçların görevin istediğini içermediğini tahmin ediyor. Bir yokluk bildirmeden önce aranan kapsamı belirt.
note-advice-completion = Bir sohbet denetimi, sonuçların görevi yanıtlayabileceğini tahmin ediyor. Yanıt vermeden önce istenen her kısmı okuduğun kaynaklarla karşılaştır.
note-progress-ended = Çalışma, ilerleme olmadan tekrarlanan aramalardan sonra bitti.
note-progress-ended-none = Anahtar sözcükle eşleşen kaynak bulunamadı.
note-progress-ended-some = Aramalar anahtar sözcükle eşleşen { $count } kaynak buldu. Ajan yanıtını tamamlamadı.
note-progress-ended-searches = Yapılan aramalar:
