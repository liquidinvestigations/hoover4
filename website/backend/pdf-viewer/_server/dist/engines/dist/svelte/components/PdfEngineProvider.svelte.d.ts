import { Snippet } from 'svelte';
import { PdfEngine } from '@embedpdf/models';
interface Props {
    children: Snippet;
    engine: PdfEngine | null;
    isLoading: boolean;
    error: Error | null;
}
declare const PdfEngineProvider: import('svelte', { with: { "resolution-mode": "import" } }).Component<Props, {}, "">;
type PdfEngineProvider = ReturnType<typeof PdfEngineProvider>;
export default PdfEngineProvider;
