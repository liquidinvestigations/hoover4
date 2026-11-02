# Translation of en/notes.ftl. Change it together with the English catalog.

## Discovery

note-discovery-l2 = שני החיפושים האחרונים לא מצאו מקור חדש. קרא עכשיו את דפי התוצאות הטובים ביותר: הכנס עד 6 מכתובות ה-URL שלהם לקריאה אחת של read_page, ברשימה `urls` שלה. חפש שוב רק עם שאלה אחרת.
note-discovery-l3-web = ענית לפני שקראת דף מקור כלשהו. קרא ל-read_page פעם אחת עם כתובות ה-URL של הדפים שתומכים בפריטים שלך, עד 6 ברשימה `urls` שלה. לאחר מכן כתוב את התשובה מחדש עם המקורות שתומכים בה.
note-discovery-l3-documents = ענית לפני שקראת מסמך כלשהו. קרא באמצעות read_documents את המסמכים שתומכים בפריטים שלך, כמה גיבובי קבצים בקריאה אחת. לאחר מכן כתוב את התשובה מחדש עם המקורות שתומכים בה.
note-discovery-l4 = קרא עכשיו את דפי התוצאות שעשויים לענות על הבקשה: הכנס עד 6 מכתובות ה-URL שלהם לקריאה אחת של read_page, ברשימה `urls` שלה. קריאה אחת קוראת את כולם בו זמנית.

## Page captures

note-capture-empty = בלכידה של { $urls } אין טקסט של מאמר. קרא מקור אחר. אל תצטט את הדף הזה.

## Sources

note-web-tools-absent = בתור הזה אין כלי אינטרנט, ולכן הוא אינו יכול לקרוא דפי אינטרנט ציבוריים. השתמש באוספים שנבחרו, וציין איזה חלק מהבקשה הם אינם עונים עליו.
note-sources-documents = חפש תחילה באוספי המסמכים המותרים. קרא את המסמכים הרלוונטיים שלהם.
note-sources-documents-before-web = חפש תחילה באוספי המסמכים המותרים. קרא את המסמכים הרלוונטיים שלהם. קרא את המסמכים האלה לפני שתשתמש ברשת.

## Named things

note-absent-collection = אין אוסף מותר בשם { $name }. האוספים המותרים הם { $collections }.
note-absent-name = באוספים שנבחרו אין התאמה באינדקס עבור { $name }.
note-absent-close-forms = צורות קרובות באינדקס: { $forms }. אל תשתמש בצורה קרובה כשם המבוקש. כשאתה מחפש צורה כזו, ציין בתשובה שזו איות אחר.
note-absent-close-form = { $form } ({ $count } מסמכים)
note-absent-web = כלי האינטרנט של התור הזה יכולים לחפש את השם.

## Search progress

note-progress-level = רמת התקדמות החיפוש { $level }.
note-progress-searches = חיפושים שכבר רצו:
note-progress-search = { $name } { $args }: { $items } פריטים, { $matches } התאמות של מילות מפתח.
note-progress-available = שלבי חיפוש שעדיין זמינים:
note-progress-complete = שלבי החיפוש הזמינים הושלמו.
note-progress-write-now = כתוב עכשיו את התשובה או את הדוח. ציין מה המקורות שקראת אינם מכילים, ופרט את החיפושים.
note-progress-answer-next = התגובה הבאה חייבת להיות התשובה. ציין את העובדות החסרות ואת החיפושים שהרצת.
note-progress-step-quoted = חפש כל שם כביטוי במרכאות באמצעות search_collections.
note-progress-step-variants = חפש מילים ללא מרכאות וגרסאות של שמות. קרא ספירות מילים ומועמדים לאיות.
note-progress-step-filters = הסר מסננים אחד אחד והרץ חיפוש בלי מסננים.
note-progress-step-facets = אמת ערכי מסננים באמצעות search_facet_values.
note-progress-step-dates = אמת תאריכים באמצעות search_histogram.
note-progress-step-passages = חפש תיאור של תוכן באמצעות search_passages.
note-progress-step-folder = השתמש ב-{ $tool } עבור התיקייה, הנתיב או הקובץ המבוקשים.
note-progress-step-read-hits = קרא את 1 עד 3 ההתאמות הטובות ביותר באמצעות { $tool }.
note-progress-step-web-search = חפש ברשת באמצעות web_search וקרא את דפי התוצאות הטובים ביותר.
note-progress-step-page-find = חפש בטקסט השמור של דף ארוך באמצעות read_page ו-find.
note-progress-step-page-retry = קרא כתובת תוצאה אחרת, או את העותק בארכיון של דף שנכשל.
note-advice-stuck = בדיקת צ'אט מעריכה שהחיפושים האחרונים חוזרים על תוצאותיהם. המיומנות no_results מתארת צורות אחרות של חיפוש.
note-advice-absent = בדיקת צ'אט מעריכה שהתוצאות אינן מכילות את מה שהמשימה דורשת. ציין את היקף החיפוש לפני שאתה מדווח על היעדר.
note-advice-completion = בדיקת צ'אט מעריכה שהתוצאות יכולות לענות על המשימה. השווה כל חלק מבוקש למקורות שקראת לפני שאתה עונה.
note-progress-ended = הריצה הסתיימה אחרי חיפושים חוזרים בלי התקדמות.
note-progress-ended-none = לא נמצא מקור שתואם למילות מפתח.
note-progress-ended-some = החיפושים מצאו { $count } מקורות שתואמים למילות מפתח. הסוכן לא השלים את התשובה שלו.
note-progress-ended-searches = חיפושים שרצו:
