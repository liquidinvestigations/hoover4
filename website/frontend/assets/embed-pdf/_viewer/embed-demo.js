import EmbedPDF from './dist/embedpdf.js';
// import EmbedPDF from '@embedpdf/snippet';
const DOC_ID = "x-pdf-viewer-doc-id";

window.demo_x_open_pdf_viewer = async function(pdf_url, callback_fn) {

const container = document.getElementById('x-demo-pdf-viewer');
  if (container) {
    window.x_pdf_viewer = EmbedPDF.init({
      type: 'container',
      target: container,
      documentManager: {
          // Load these files on startup
          initialDocuments: [
            {
              url: pdf_url,
              // By default, autoActivate is true.
              // This document will open and become active.
              autoActivate: true,
              // OPTIONAL: Set a custom ID so you can easily reference
              // this document later (e.g. to scroll or close it).
              documentId: DOC_ID,
            },
          ]
      },
      theme: { preference: 'light' },
      disabledCategories: [
          'annotation',
          'print',
          'redaction',
          'export',
          'document',
          'shapes',
          'zoom',
          'tools',
          'page',
          'sidebars',
          'panel',
          'spread','rotate', 'scroll',
      ],
    });

    const registry = await window.x_pdf_viewer.registry;

      // 1. Get the plugins
      const commands = registry.getPlugin('commands').provides();
      const ui = registry.getPlugin('ui').provides();

    // 4. Replace a button in the toolbar
      const schema = ui.getSchema();
      console.log("UI SCHEMA: ", schema);
      schema.toolbars = {};
      schema.overlays = {};
      schema.selectionMenus = {};

      const scroll = registry.getPlugin('scroll').provides();
      const search = registry.getPlugin('search').provides();
      console.log("SEARCH PLUGIN: ", search);
      scroll.onLayoutReady((event) => {callback_fn(event, scroll, search);});

  } else {
    console.error("PDF CONTAINER NOT FOUND: ", container);
    return null;
  }
}
// const pdf_url ='http://localhost:8080/_download_document/testdata/a0d06de0243c63497070c77e9bb6cab5a2d0bda5564daa03a37987a4f1640fd3';
const pdf_url ='https://snippet.embedpdf.com/ebook.pdf';
function callback_fn(event, scroll, search) {

  console.log("LAYOUT READY: ", event);
  console.log("DOC TOTAL PAGES: ", event.totalPages);
    // scroll.scrollToPage({
        // pageNumber: 2,
        // behavior: 'instant' // Instant jump for initial load
    // });
    const PAGE_IDX = 12;
    const search_result = search.searchAllPages('PDF', DOC_ID).toPromise();
    search_result.then((result) => {
        console.log("SEARCH RESULT: ", result);
        let item = result.results[PAGE_IDX];
        let page_index = item.pageIndex;
        let point = item.rects[0].origin;
        let individual_result = search.goToResult(PAGE_IDX, DOC_ID);
        scroll.scrollToPage({
          pageNumber: page_index+1,
          behavior: 'smooth',
          pageCoordinates: point,
          alignY: 40,
        }, DOC_ID);
        console.log("INDIVIDUAL RESULT: ", individual_result);
        console.log("GET FLAG: ", search.getState());
    });

}



const RESULT={
  "results": [
    {
      "pageIndex": 0,
      "charIndex": 5,
      "charCount": 3,
      "rects": [
        {
          "origin": {
            "x": 381.34783935546875,
            "y": 124.7833251953125
          },
          "size": {
            "width": 28,
            "height": 37
          }
        },
        {
          "origin": {
            "x": 413.7528076171875,
            "y": 124.7833251953125
          },
          "size": {
            "width": 31,
            "height": 37
          }
        },
        {
          "origin": {
            "x": 449.85955810546875,
            "y": 124.7833251953125
          },
          "size": {
            "width": 24,
            "height": 37
          }
        }
      ],
      "context": {
        "before": "Embed",
        "match": "PDF",
        "after": " PDF Viewers Are a Pain But they Don’t",
        "truncatedLeft": false,
        "truncatedRight": true
      }
    },
    {
      "pageIndex": 0,
      "charIndex": 10,
      "charCount": 3,
      "rects": [
        {
          "origin": {
            "x": 109.1958999633789,
            "y": 228.4248046875
          },
          "size": {
            "width": 21,
            "height": 30
          }
        },
        {
          "origin": {
            "x": 134.8677215576172,
            "y": 228.4248046875
          },
          "size": {
            "width": 24,
            "height": 30
          }
        },
        {
          "origin": {
            "x": 163.74014282226562,
            "y": 228.4248046875
          },
          "size": {
            "width": 19,
            "height": 30
          }
        }
      ],
      "context": {
        "before": "EmbedPDF ",
        "match": "PDF",
        "after": " Viewers Are a Pain But they Don’t Have",
        "truncatedLeft": false,
        "truncatedRight": true
      }
    },
    {
      "pageIndex": 0,
      "charIndex": 73,
      "charCount": 3,
      "rects": [
        {
          "origin": {
            "x": 266.1478576660156,
            "y": 391.78973388671875
          },
          "size": {
            "width": 13,
            "height": 21
          }
        },
        {
          "origin": {
            "x": 283.4276123046875,
            "y": 391.78973388671875
          },
          "size": {
            "width": 16,
            "height": 21
          }
        },
        {
          "origin": {
            "x": 303.48699951171875,
            "y": 391.78973388671875
          },
          "size": {
            "width": 12,
            "height": 21
          }
        }
      ],
      "context": {
        "before": "Pain But they Don’t Have to Be) How Embed",
        "match": "PDF",
        "after": " is Making PDF Integration Actually",
        "truncatedLeft": true,
        "truncatedRight": true
      }
    },
    {
      "pageIndex": 0,
      "charIndex": 88,
      "charCount": 3,
      "rects": [
        {
          "origin": {
            "x": 108.90784454345703,
            "y": 425.79754638671875
          },
          "size": {
            "width": 13,
            "height": 21
          }
        },
        {
          "origin": {
            "x": 126.18759155273438,
            "y": 425.79754638671875
          },
          "size": {
            "width": 16,
            "height": 21
          }
        },
        {
          "origin": {
            "x": 146.2469940185547,
            "y": 425.79754638671875
          },
          "size": {
            "width": 12,
            "height": 21
          }
        }
      ],
      "context": {
        "before": "Don’t Have to Be) How EmbedPDF is Making ",
        "match": "PDF",
        "after": " Integration Actually Enjoyable Bob",
        "truncatedLeft": true,
        "truncatedRight": true
      }
    },
    {
      "pageIndex": 0,
      "charIndex": 137,
      "charCount": 3,
      "rects": [
        {
          "origin": {
            "x": 413.5476989746094,
            "y": 640.0585021972656
          },
          "size": {
            "width": 17,
            "height": 22
          }
        },
        {
          "origin": {
            "x": 432.9925842285156,
            "y": 640.0585021972656
          },
          "size": {
            "width": 19,
            "height": 22
          }
        },
        {
          "origin": {
            "x": 454.6588134765625,
            "y": 640.0585021972656
          },
          "size": {
            "width": 15,
            "height": 22
          }
        }
      ],
      "context": {
        "before": "Integration Actually Enjoyable Bob Singor ",
        "match": "PDF",
        "after": "",
        "truncatedLeft": true,
        "truncatedRight": false
      }
    },
    {
      "pageIndex": 1,
      "charIndex": 15,
      "charCount": 3,
      "rects": [
        {
          "origin": {
            "x": 246.269287109375,
            "y": 65.06622314453125
          },
          "size": {
            "width": 17,
            "height": 22
          }
        },
        {
          "origin": {
            "x": 265.7142028808594,
            "y": 65.06622314453125
          },
          "size": {
            "width": 19,
            "height": 22
          }
        },
        {
          "origin": {
            "x": 287.38043212890625,
            "y": 65.06622314453125
          },
          "size": {
            "width": 15,
            "height": 22
          }
        }
      ],
      "context": {
        "before": "Let's face it: ",
        "match": "PDF",
        "after": " integration sucks. You need PDF functionality",
        "truncatedLeft": false,
        "truncatedRight": true
      }
    },
    {
      "pageIndex": 1,
      "charIndex": 49,
      "charCount": 3,
      "rects": [
        {
          "origin": {
            "x": 156.20809936523438,
            "y": 191.70538330078125
          },
          "size": {
            "width": 10,
            "height": 15
          }
        },
        {
          "origin": {
            "x": 168.9783477783203,
            "y": 191.70538330078125
          },
          "size": {
            "width": 12,
            "height": 15
          }
        },
        {
          "origin": {
            "x": 183.4083251953125,
            "y": 191.70538330078125
          },
          "size": {
            "width": 9,
            "height": 15
          }
        }
      ],
      "context": {
        "before": "face it: PDF integration sucks. You need ",
        "match": "PDF",
        "after": " functionality in your app. Your users",
        "truncatedLeft": true,
        "truncatedRight": true
      }
    },
    {
      "pageIndex": 1,
      "charIndex": 189,
      "charCount": 3,
      "rects": [
        {
          "origin": {
            "x": 119.73566436767578,
            "y": 320.70538330078125
          },
          "size": {
            "width": 10,
            "height": 15
          }
        },
        {
          "origin": {
            "x": 132.5059051513672,
            "y": 320.70538330078125
          },
          "size": {
            "width": 12,
            "height": 15
          }
        },
        {
          "origin": {
            "x": 146.93589782714844,
            "y": 320.70538330078125
          },
          "size": {
            "width": 9,
            "height": 15
          }
        }
      ],
      "context": {
        "before": "Pay through the nose for a commercial ",
        "match": "PDF",
        "after": " SDK that locks you into their ecosystem",
        "truncatedLeft": true,
        "truncatedRight": true
      }
    },
    {
      "pageIndex": 2,
      "charIndex": 11,
      "charCount": 3,
      "rects": [
        {
          "origin": {
            "x": 245.01275634765625,
            "y": 65.06622314453125
          },
          "size": {
            "width": 17,
            "height": 22
          }
        },
        {
          "origin": {
            "x": 264.4576721191406,
            "y": 65.06622314453125
          },
          "size": {
            "width": 19,
            "height": 22
          }
        },
        {
          "origin": {
            "x": 286.1238708496094,
            "y": 65.06622314453125
          },
          "size": {
            "width": 15,
            "height": 22
          }
        }
      ],
      "context": {
        "before": "Enter Embed",
        "match": "PDF",
        "after": " The PDF viewer that doesn't make you",
        "truncatedLeft": false,
        "truncatedRight": true
      }
    },
    {
      "pageIndex": 2,
      "charIndex": 20,
      "charCount": 3,
      "rects": [
        {
          "origin": {
            "x": 384.5472717285156,
            "y": 65.06622314453125
          },
          "size": {
            "width": 17,
            "height": 22
          }
        },
        {
          "origin": {
            "x": 403.9921569824219,
            "y": 65.06622314453125
          },
          "size": {
            "width": 19,
            "height": 22
          }
        },
        {
          "origin": {
            "x": 425.65838623046875,
            "y": 65.06622314453125
          },
          "size": {
            "width": 15,
            "height": 22
          }
        }
      ],
      "context": {
        "before": "Enter EmbedPDF The ",
        "match": "PDF",
        "after": " viewer that doesn't make you choose between",
        "truncatedLeft": false,
        "truncatedRight": true
      }
    },
    {
      "pageIndex": 2,
      "charIndex": 114,
      "charCount": 3,
      "rects": [
        {
          "origin": {
            "x": 206.59317016601562,
            "y": 263.70538330078125
          },
          "size": {
            "width": 10,
            "height": 15
          }
        },
        {
          "origin": {
            "x": 219.36343383789062,
            "y": 263.70538330078125
          },
          "size": {
            "width": 12,
            "height": 15
          }
        },
        {
          "origin": {
            "x": 233.79339599609375,
            "y": 263.70538330078125
          },
          "size": {
            "width": 9,
            "height": 15
          }
        }
      ],
      "context": {
        "before": "wallet and your sanity We built Embed",
        "match": "PDF",
        "after": " because we were tired of the same frustrating",
        "truncatedLeft": true,
        "truncatedRight": true
      }
    },
    {
      "pageIndex": 2,
      "charIndex": 265,
      "charCount": 3,
      "rects": [
        {
          "origin": {
            "x": 310.34649658203125,
            "y": 359.70538330078125
          },
          "size": {
            "width": 10,
            "height": 15
          }
        },
        {
          "origin": {
            "x": 323.1167297363281,
            "y": 359.70538330078125
          },
          "size": {
            "width": 12,
            "height": 15
          }
        },
        {
          "origin": {
            "x": 337.5467224121094,
            "y": 359.70538330078125
          },
          "size": {
            "width": 9,
            "height": 15
          }
        }
      ],
      "context": {
        "before": "free libraries. Here's what makes Embed",
        "match": "PDF",
        "after": " different: 1 It's 100% open-source with",
        "truncatedLeft": true,
        "truncatedRight": true
      }
    },
    {
      "pageIndex": 2,
      "charIndex": 479,
      "charCount": 3,
      "rects": [
        {
          "origin": {
            "x": 268.0747375488281,
            "y": 564.7132263183594
          },
          "size": {
            "width": 10,
            "height": 15
          }
        },
        {
          "origin": {
            "x": 280.844970703125,
            "y": 564.7132263183594
          },
          "size": {
            "width": 12,
            "height": 15
          }
        },
        {
          "origin": {
            "x": 295.27496337890625,
            "y": 564.7132263183594
          },
          "size": {
            "width": 9,
            "height": 15
          }
        }
      ],
      "context": {
        "before": "Angular, Svelte... we don't care) 3 It's powered by ",
        "match": "PDF",
        "after": "ium - the same engine Google uses in Chrome",
        "truncatedLeft": true,
        "truncatedRight": true
      }
    },
    {
      "pageIndex": 3,
      "charIndex": 9,
      "charCount": 3,
      "rects": [
        {
          "origin": {
            "x": 183.51841735839844,
            "y": 67.05841064453125
          },
          "size": {
            "width": 17,
            "height": 22
          }
        },
        {
          "origin": {
            "x": 202.9633331298828,
            "y": 67.05841064453125
          },
          "size": {
            "width": 19,
            "height": 22
          }
        },
        {
          "origin": {
            "x": 224.62954711914062,
            "y": 67.05841064453125
          },
          "size": {
            "width": 15,
            "height": 22
          }
        }
      ],
      "context": {
        "before": "Join the ",
        "match": "PDF",
        "after": " revolution Every developer who switches",
        "truncatedLeft": false,
        "truncatedRight": true
      }
    },
    {
      "pageIndex": 3,
      "charIndex": 63,
      "charCount": 3,
      "rects": [
        {
          "origin": {
            "x": 124.4164810180664,
            "y": 189.71319580078125
          },
          "size": {
            "width": 10,
            "height": 15
          }
        },
        {
          "origin": {
            "x": 137.1867218017578,
            "y": 189.71319580078125
          },
          "size": {
            "width": 12,
            "height": 15
          }
        },
        {
          "origin": {
            "x": 151.61671447753906,
            "y": 189.71319580078125
          },
          "size": {
            "width": 9,
            "height": 15
          }
        }
      ],
      "context": {
        "before": "Every developer who switches to Embed",
        "match": "PDF",
        "after": " strengthens our community and helps",
        "truncatedLeft": true,
        "truncatedRight": true
      }
    },
    {
      "pageIndex": 3,
      "charIndex": 156,
      "charCount": 3,
      "rects": [
        {
          "origin": {
            "x": 246.68077087402344,
            "y": 261.71319580078125
          },
          "size": {
            "width": 10,
            "height": 15
          }
        },
        {
          "origin": {
            "x": 259.4510192871094,
            "y": 261.71319580078125
          },
          "size": {
            "width": 12,
            "height": 15
          }
        },
        {
          "origin": {
            "x": 273.8810119628906,
            "y": 261.71319580078125
          },
          "size": {
            "width": 9,
            "height": 15
          }
        }
      ],
      "context": {
        "before": "product for everyone. By choosing Embed",
        "match": "PDF",
        "after": ", you're not just making a technical decision",
        "truncatedLeft": true,
        "truncatedRight": true
      }
    },
    {
      "pageIndex": 3,
      "charIndex": 298,
      "charCount": 3,
      "rects": [
        {
          "origin": {
            "x": 342.40875244140625,
            "y": 333.71319580078125
          },
          "size": {
            "width": 10,
            "height": 15
          }
        },
        {
          "origin": {
            "x": 355.17901611328125,
            "y": 333.71319580078125
          },
          "size": {
            "width": 12,
            "height": 15
          }
        },
        {
          "origin": {
            "x": 369.6089782714844,
            "y": 333.71319580078125
          },
          "size": {
            "width": 9,
            "height": 15
          }
        }
      ],
      "context": {
        "before": "that fundamental functionality like ",
        "match": "PDF",
        "after": " viewing shouldn't be locked behind expensive",
        "truncatedLeft": true,
        "truncatedRight": true
      }
    },
    {
      "pageIndex": 3,
      "charIndex": 435,
      "charCount": 3,
      "rects": [
        {
          "origin": {
            "x": 124.4164810180664,
            "y": 453.71319580078125
          },
          "size": {
            "width": 10,
            "height": 15
          }
        },
        {
          "origin": {
            "x": 137.1867218017578,
            "y": 453.71319580078125
          },
          "size": {
            "width": 12,
            "height": 15
          }
        },
        {
          "origin": {
            "x": 151.61671447753906,
            "y": 453.71319580078125
          },
          "size": {
            "width": 9,
            "height": 15
          }
        }
      ],
      "context": {
        "before": "GitHub repository today to see Embed",
        "match": "PDF",
        "after": " in action, and free yourself from the",
        "truncatedLeft": true,
        "truncatedRight": true
      }
    },
    {
      "pageIndex": 3,
      "charIndex": 478,
      "charCount": 3,
      "rects": [
        {
          "origin": {
            "x": 94.38494110107422,
            "y": 477.71319580078125
          },
          "size": {
            "width": 10,
            "height": 15
          }
        },
        {
          "origin": {
            "x": 107.15518951416016,
            "y": 477.71319580078125
          },
          "size": {
            "width": 12,
            "height": 15
          }
        },
        {
          "origin": {
            "x": 121.58516693115234,
            "y": 477.71319580078125
          },
          "size": {
            "width": 9,
            "height": 15
          }
        }
      ],
      "context": {
        "before": "in action, and free yourself from the ",
        "match": "PDF",
        "after": " integration pain once and for all. 4",
        "truncatedLeft": true,
        "truncatedRight": false
      }
    }
  ],
  "total": 19
};



await window.demo_x_open_pdf_viewer(pdf_url,
  (event, scroll, search) => {
    console.log("LAYOUT READY: ", event);
  console.log("DOC TOTAL PAGES: ", event.totalPages);
    // scroll.scrollToPage({
        // pageNumber: 2,
        // behavior: 'instant' // Instant jump for initial load
    // });
    const PAGE_IDX = 12;
    // const search_result = search.searchAllPages('PDF', DOC_ID).toPromise();
    search.startSearch(DOC_ID);
    search.setShowAllResults(true, DOC_ID);
    search.setExternalSearchResults(DOC_ID, RESULT);
    console.log("SET EXTERNAL SEARCH RESULTS: ", search.getState());
    // search.stopSearch(DOC_ID);
    // search.goToResult(0, DOC_ID);
    // search.searchResult$.emit({documentId: DOC_ID, results: RESULT});
    // search_result.then((result) => {
    //     console.log("SEARCH RESULT: ", result);
    //     let item = result.results[PAGE_IDX];
    //     let page_index = item.pageIndex;
    //     let point = item.rects[0].origin;
    //     let individual_result = search.goToResult(PAGE_IDX, DOC_ID);
    //     scroll.scrollToPage({
    //       pageNumber: page_index+1,
    //       behavior: 'smooth',
    //       pageCoordinates: point,
    //       alignY: 40,
    //     }, DOC_ID);
    //     console.log("INDIVIDUAL RESULT: ", individual_result);
    //     console.log("GET FLAG: ", search.getState());
    // });
  }
);