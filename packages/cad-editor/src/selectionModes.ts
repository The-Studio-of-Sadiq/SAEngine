/** Stateful set operations shared by interactive selection and SELECT commands. */

export type SelectionMode = 'add' | 'remove';

export class SelectionWorkingSet<T> {
	private values = new Set<T>();
	private history: Set<T>[] = [];
	mode: SelectionMode = 'add';

	constructor(initial: Iterable<T> = []) {
		this.values = new Set(initial);
	}

	get ids(): readonly T[] {
		return [...this.values];
	}

	apply(ids: Iterable<T>): void {
		this.history.push(new Set(this.values));
		for (const id of ids) {
			if (this.mode === 'add') {
				this.values.add(id);
			} else {
				this.values.delete(id);
			}
		}
	}

	undo(): void {
		const previous = this.history.pop();
		if (previous) {
			this.values = previous;
		}
	}

	set(ids: Iterable<T>): void {
		this.values = new Set(ids);
		this.history = [];
	}
}

let lastCommittedSelection: readonly string[] = [];

export function getPreviousSelection(): readonly string[] {
	return [...lastCommittedSelection];
}

export function setPreviousSelection(ids: readonly string[]): void {
	lastCommittedSelection = [...ids];
}

export interface SelectionEntityLike {
	readonly objectId: unknown;
	readonly dxfTypeName?: string;
	readonly layer?: string;
	readonly color?: unknown;
}

export interface SelectionFilters {
	readonly type?: string;
	readonly layer?: string;
	readonly color?: string;
}

export function filterSelection<T extends SelectionEntityLike>(entities: readonly T[], filters: SelectionFilters): T[] {
	return entities.filter(entity =>
		(!filters.type || entity.dxfTypeName?.toUpperCase() === filters.type.toUpperCase()) &&
		(!filters.layer || entity.layer?.toUpperCase() === filters.layer.toUpperCase()) &&
		(!filters.color || String(entity.color).toUpperCase() === filters.color.toUpperCase()),
	);
}
