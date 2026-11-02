# Translation of en/notes.ftl. Change it together with the English catalog.

## Discovery

note-discovery-l2 = पिछली दो खोजों में कोई नया स्रोत नहीं मिला। अब सबसे अच्छे परिणाम पेज पढ़ें: उनके अधिकतम 6 URL एक ही read_page कॉल में, उसकी `urls` सूची में रखें। दोबारा खोजें तो केवल किसी अलग प्रश्न से।
note-discovery-l3-web = आपने कोई स्रोत पेज पढ़े बिना उत्तर दे दिया। उन पेजों के URL के साथ read_page को एक बार कॉल करें जो आपकी मदों का समर्थन करते हैं, उसकी `urls` सूची में अधिकतम 6। फिर उन स्रोतों के साथ उत्तर दोबारा लिखें जो उसका समर्थन करते हैं।
note-discovery-l3-documents = आपने कोई दस्तावेज़ पढ़े बिना उत्तर दे दिया। जो दस्तावेज़ आपकी मदों का समर्थन करते हैं उन्हें read_documents से पढ़ें, एक कॉल में कई फ़ाइल हैश। फिर उन स्रोतों के साथ उत्तर दोबारा लिखें जो उसका समर्थन करते हैं।
note-discovery-l4 = अब वे परिणाम पेज पढ़ें जो अनुरोध का उत्तर दे सकते हैं: उनके अधिकतम 6 URL एक ही read_page कॉल में, उसकी `urls` सूची में रखें। एक कॉल उन सभी को एक साथ पढ़ती है।

## Page captures

note-capture-empty = { $urls } के कैप्चर में लेख का कोई टेक्स्ट नहीं है। कोई दूसरा स्रोत पढ़ें। इस पेज का उद्धरण न दें।

## Sources

note-web-tools-absent = इस टर्न में वेब टूल नहीं हैं, इसलिए यह सार्वजनिक वेब पेज नहीं पढ़ सकता। चुने गए संग्रहों का उपयोग करें, और बताएँ कि अनुरोध का कौन-सा भाग वे पूरा नहीं करते।
note-sources-documents = पहले अनुमत दस्तावेज़ संग्रहों में खोजें। उनके प्रासंगिक दस्तावेज़ पढ़ें।
note-sources-documents-before-web = पहले अनुमत दस्तावेज़ संग्रहों में खोजें। उनके प्रासंगिक दस्तावेज़ पढ़ें। वेब का उपयोग करने से पहले उन दस्तावेज़ों को पढ़ें।

## Named things

note-absent-collection = किसी भी अनुमत संग्रह का नाम { $name } नहीं है। अनुमत संग्रह ये हैं: { $collections }।
note-absent-name = चुने गए संग्रहों में { $name } के लिए कोई इंडेक्स किया हुआ मिलान नहीं है।
note-absent-close-forms = इंडेक्स किए हुए मिलते-जुलते रूप: { $forms }। किसी मिलते-जुलते रूप को माँगे गए नाम की तरह न लें। जब आप उनमें से किसी को खोजें, तो उत्तर में उसे अलग वर्तनी के रूप में बताएँ।
note-absent-close-form = { $form } ({ $count } दस्तावेज़)
note-absent-web = इस टर्न के वेब टूल इस नाम को खोज सकते हैं।

## Search progress

note-progress-level = खोज प्रगति का स्तर { $level }।
note-progress-searches = अब तक चलाई गई खोजें:
note-progress-search = { $name } { $args }: { $items } आइटम, { $matches } कीवर्ड मिलान।
note-progress-available = अभी उपलब्ध खोज चरण:
note-progress-complete = उपलब्ध खोज चरण पूरे हो चुके हैं।
note-progress-write-now = अब उत्तर या रिपोर्ट लिखें। बताएँ कि पढ़े गए स्रोतों में क्या नहीं है और खोजों के नाम लिखें।
note-progress-answer-next = अगला उत्तर ही अंतिम उत्तर होना चाहिए। छूटे हुए तथ्य और आपकी चलाई गई खोजें बताएँ।
note-progress-step-quoted = हर नाम को search_collections से उद्धरण चिह्नों वाले वाक्यांश के रूप में खोजें।
note-progress-step-variants = बिना उद्धरण चिह्न के शब्द और नाम के रूपांतर खोजें। शब्द गणना और वर्तनी के उम्मीदवार पढ़ें।
note-progress-step-filters = फ़िल्टर एक-एक करके हटाएँ और बिना फ़िल्टर के खोज चलाएँ।
note-progress-step-facets = search_facet_values से फ़िल्टर के मान जाँचें।
note-progress-step-dates = search_histogram से तारीख़ें जाँचें।
note-progress-step-passages = search_passages से सामग्री के विवरण को खोजें।
note-progress-step-folder = माँगे गए फ़ोल्डर, पथ या फ़ाइल के लिए { $tool } का उपयोग करें।
note-progress-step-read-hits = { $tool } से सबसे अच्छे 1 से 3 परिणाम पढ़ें।
note-progress-step-web-search = web_search से वेब पर खोजें और सबसे अच्छे परिणाम पेज पढ़ें।
note-progress-step-page-find = read_page और find से किसी लंबे पेज के रखे गए टेक्स्ट में खोजें।
note-progress-step-page-retry = कोई दूसरा परिणाम पता पढ़ें, या विफल पेज की आर्काइव प्रति पढ़ें।
note-advice-stuck = एक चैट जाँच का अनुमान है कि हाल की खोजें अपने परिणाम दोहरा रही हैं। no_results स्किल खोज के अन्य रूप बताती है।
note-advice-absent = एक चैट जाँच का अनुमान है कि परिणामों में वह नहीं है जो कार्य माँगता है। किसी अनुपस्थिति की रिपोर्ट करने से पहले खोजा गया दायरा बताएँ।
note-advice-completion = एक चैट जाँच का अनुमान है कि परिणाम कार्य का उत्तर दे सकते हैं। उत्तर देने से पहले माँगे गए हर भाग की तुलना उन स्रोतों से करें जिन्हें आपने पढ़ा है।
note-progress-ended = बार-बार की खोजों के बाद, बिना प्रगति के, रन समाप्त हो गया।
note-progress-ended-none = कीवर्ड से मेल खाने वाला कोई स्रोत नहीं मिला।
note-progress-ended-some = खोजों में कीवर्ड से मेल खाने वाले { $count } स्रोत मिले। एजेंट ने अपना उत्तर पूरा नहीं किया।
note-progress-ended-searches = चलाई गई खोजें:
