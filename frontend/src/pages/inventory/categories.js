import { createContext, useContext } from "react";
import {
  Armchair, Box, Cable, HardDrive, Headphones, Keyboard, Laptop, MemoryStick, Monitor, Mouse, Package, Plug, Printer,
  Smartphone, Tag, Wrench,
} from "lucide-react";
import { api } from "../../lib/api";

// the icons a category can show (catalog.ProductCategory.ICONS)
export const ICONS = {
  laptop: Laptop, plug: Plug, "hard-drive": HardDrive, memory: MemoryStick, headphones: Headphones, package: Package,
  monitor: Monitor, printer: Printer, smartphone: Smartphone, keyboard: Keyboard, mouse: Mouse, cable: Cable,
  armchair: Armchair, box: Box, tag: Tag, wrench: Wrench,
};

// a field as the server keeps it -> as the Add stock form draws it
const toFormField = (f) => ({
  key: f.key, label: f.label, required: !!f.required, placeholder: f.placeholder || undefined,
  options: f.type === "choice" ? f.options : undefined, suggest: f.type === "text" && f.suggest?.length ? f.suggest : undefined,
  textarea: f.type === "long", wide: f.type === "long",
});

/* The product categories as the Admin has set them up, ready for the form. */
export function categoryRegistry(list) {
  const all = (list || []).map((c) => ({ ...c, Icon: ICONS[c.icon] || Package, specFields: (c.fields || []).map(toFormField) }));
  return { all, active: all.filter((c) => c.is_active), byKey: Object.fromEntries(all.map((c) => [c.key, c])) };
}

export const loadCategories = () => api.get("/product-categories/").then((d) => d.results ?? d);

export const CategoryContext = createContext(categoryRegistry([]));
export const useCategories = () => useContext(CategoryContext);
