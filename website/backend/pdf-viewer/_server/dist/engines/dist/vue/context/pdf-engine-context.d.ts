import { InjectionKey, Ref } from 'vue';
import { PdfEngine } from '@embedpdf/models';
export interface PdfEngineContextState {
    engine: Ref<PdfEngine | null>;
    isLoading: Ref<boolean>;
    error: Ref<Error | null>;
}
export declare const pdfEngineKey: InjectionKey<PdfEngineContextState>;
