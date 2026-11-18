// Finds and loads the parameter metadata: the machine-scoped setting path,
// else `build/*/parameters.json` under each workspace folder (a QuickPick when
// several exist, the choice remembered per workspace), else none. No
// `vscode` import: the picker and the workspace memory are injected.
import * as fs from 'fs';
import * as path from 'path';
import { parseParameterMetadata, ParameterMetadataSet } from './parameter-metadata';

const REMEMBER_KEY = 'px4Gcs.parameters.metadataChoice';

export interface MetadataLoaderOptions {
  settingPath(): string;
  workspaceFolders(): string[];
  /** Choose one of several files; undefined when the operator dismisses the pick. */
  pick(files: string[]): Promise<string | undefined>;
  memory: { get(key: string): string | undefined; update(key: string, value: string | undefined): Thenable<void> | Promise<void> };
  log(line: string): void;
}

/** Every `build/<target>/parameters.json` directly under the given roots, sorted. */
export function discoverMetadataFiles(roots: string[]): string[] {
  const found: string[] = [];
  for (const root of roots) {
    const build = path.join(root, 'build');
    let targets: string[] = [];
    try {
      targets = fs.readdirSync(build);
    } catch {
      continue;
    }
    for (const target of targets) {
      const file = path.join(build, target, 'parameters.json');
      if (fs.existsSync(file)) found.push(file);
    }
  }
  return found.sort();
}

export function loadMetadataFile(file: string): ParameterMetadataSet {
  return parseParameterMetadata(fs.readFileSync(file, 'utf8'), file);
}

export class ParameterMetadataLoader {
  constructor(private readonly options: MetadataLoaderOptions) {}

  /** The metadata to use now, or undefined. `choose` asks again even when a choice is remembered. */
  async resolve(choose = false): Promise<ParameterMetadataSet | undefined> {
    const { options } = this;
    const setting = options.settingPath();
    if (setting) return this.tryLoad(setting);
    const files = discoverMetadataFiles(options.workspaceFolders());
    if (files.length === 0) return undefined;
    const remembered = options.memory.get(REMEMBER_KEY);
    let file: string | undefined;
    if (files.length === 1) file = files[0];
    else if (!choose && remembered && files.includes(remembered)) file = remembered;
    else file = await options.pick(files);
    if (!file) return undefined;
    if (files.length > 1) await options.memory.update(REMEMBER_KEY, file);
    return this.tryLoad(file);
  }

  private tryLoad(file: string): ParameterMetadataSet | undefined {
    try {
      return loadMetadataFile(file);
    } catch (error) {
      this.options.log(`parameter metadata ${file}: ${error instanceof Error ? error.message : String(error)}`);
      return undefined;
    }
  }
}
