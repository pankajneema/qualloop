import type { ReactNode } from 'react';

export type Column<T> = {
  id: string;
  header: string;
  cell: (row: T) => ReactNode;
  /** Hidden below 640 px so a phone never scrolls sideways; put the key facts in a visible column. */
  hideOnPhone?: boolean;
  mono?: boolean;
};

/** Dense table: 40 px rows, label-style headers, borders instead of shadows. Keyset paging lives in the caller. */
export function DataTable<T>({
  label,
  columns,
  rows,
  rowKey,
  dim = false,
}: {
  label: string;
  columns: Column<T>[];
  rows: T[];
  rowKey: (row: T) => string;
  /** True while a new query loads over the old rows. */
  dim?: boolean;
}) {
  return (
    <div className="border-line-soft bg-surface rounded-card border">
      <table
        aria-label={label}
        aria-busy={dim}
        className={`w-full border-collapse text-left ${dim ? 'opacity-60' : ''}`}
      >
        <thead>
          <tr>
            {columns.map((c) => (
              <th
                key={c.id}
                scope="col"
                className={`text-label text-muted border-line border-b px-12 py-8 uppercase ${
                  c.hideOnPhone ? 'hidden sm:table-cell' : ''
                }`}
              >
                {c.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={rowKey(row)} className="border-line-soft h-row border-b last:border-b-0">
              {columns.map((c) => (
                <td
                  key={c.id}
                  className={`text-body text-ink-2 px-12 py-8 align-middle break-words ${
                    c.hideOnPhone ? 'hidden sm:table-cell' : ''
                  } ${c.mono ? 'text-data font-mono' : ''}`}
                >
                  {c.cell(row)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
