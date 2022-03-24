from pathlib import Path
import re

from docutils import nodes
from docutils import transforms
from sphinx import errors

from pep_sphinx_extensions.pep_processor.transforms import pep_zero
from pep_sphinx_extensions.pep_processor.transforms.pep_zero import _mask_email


class PEPParsingError(errors.SphinxError):
    pass


# PEPHeaders is identical to docutils.transforms.peps.Headers excepting bdfl-delegate, sponsor & superseeded-by
class PEPHeaders(transforms.Transform):
    """Process fields in a PEP's initial RFC-2822 header."""

    # Run before pep_processor.transforms.pep_title.PEPTitle
    default_priority = 330

    def apply(self) -> None:
        if not Path(self.document["source"]).match("pep-*"):
            return  # not a PEP file, exit early

        if not len(self.document):
            raise PEPParsingError("Document tree is empty.")

        header = self.document[0]
        if not isinstance(header, nodes.field_list) or "rfc2822" not in header["classes"]:
            raise PEPParsingError("Document does not begin with an RFC-2822 header; it is not a PEP.")

        # PEP number should be the first field
        pep_field = header[0]
        if pep_field[0].astext().lower() != "pep":
            raise PEPParsingError("Document does not contain an RFC-2822 'PEP' header!")

        # Extract PEP number
        value = pep_field[1].astext()
        try:
            pep_num = int(value)
        except ValueError:
            raise PEPParsingError(f"'PEP' header must contain an integer. '{value}' is invalid!")

        # Special processing for PEP 0.
        if pep_num == 0:
            pending = nodes.pending(pep_zero.PEPZero)
            self.document.insert(1, pending)
            self.document.note_pending(pending)

        # If there are less than two headers in the preamble, or if Title is absent
        if len(header) < 2 or header[1][0].astext().lower() != "title":
            raise PEPParsingError("No title!")

        fields_to_remove = []
        for field in header:
            name = field[0].astext().lower()
            body = field[1]
            if len(body) == 0:
                # body is empty
                continue
            elif len(body) > 1:
                msg = f"PEP header field body contains multiple elements:\n{field.pformat(level=1)}"
                raise PEPParsingError(msg)
            elif not isinstance(body[0], nodes.paragraph):  # len(body) == 1
                msg = f"PEP header field body may only contain a single paragraph:\n{field.pformat(level=1)}"
                raise PEPParsingError(msg)

            para = body[0]
            if name in {"author", "bdfl-delegate", "pep-delegate", "sponsor"}:
                # mask emails
                for node in para:
                    if not isinstance(node, nodes.reference):
                        continue
                    node.replace_self(_mask_email(node))
            elif name in {"discussions-to", "resolution"}:
                # only handle threads, email addresses in Discussions-To aren't
                # masked.
                for node in para:
                    if not isinstance(node, nodes.reference):
                        continue
                    if node["refuri"].startswith("https://mail.python.org"):
                        node[0] = _pretty_thread(node[0])
            elif name in {"replaces", "superseded-by", "requires"}:
                # replace PEP numbers with normalised list of links to PEPs
                new_body = []
                for pep_str in re.split(r",?\s+", body.astext()):
                    target = self.document.settings.pep_url.format(int(pep_str))
                    new_body += [nodes.reference("", pep_str, refuri=target), nodes.Text(", ")]
                para[:] = new_body[:-1]  # drop trailing space
            elif name in {"last-modified", "content-type", "version"}:
                # Mark unneeded fields
                fields_to_remove.append(field)

        # Remove unneeded fields
        for field in fields_to_remove:
            field.parent.remove(field)


def _process_list_url(list_url: str) -> tuple[str, str]:
    url_type = "list"
    parts = list_url.lower().strip().strip("/").split("/")

    # HyperKitty (Mailman3) archive structure is
    # https://mail.python.org/archives/list/<list_name>/thread/<id>
    if "archives" in parts:
        list_name = (
            parts[parts.index("archives") + 2].removesuffix("@python.org"))
        if len(parts) > 6 and parts[6] in {"message", "thread"}:
            url_type = parts[6]

    # Mailman3 list info structure is
    # https://mail.python.org/mailman3/lists/<list_name>.python.org/
    elif "mailman3" in parts:
        list_name = (
            parts[parts.index("mailman3") + 2].removesuffix(".python.org"))

    # Pipermail (Mailman) archive structure is
    # https://mail.python.org/pipermail/<list_name>/<month>-<year>/<id>
    elif "pipermail" in parts:
        list_name = parts[parts.index("pipermail") + 1]
        url_type = "message" if len(parts) > 6 else "list"

    # Mailman listinfo structure is
    # https://mail.python.org/mailman/listinfo/<list_name>
    elif "listinfo" in parts:
        list_name = parts[parts.index("listinfo") + 1]

    # Not a link to a mailing list, message or thread
    else:
        raise ValueError("Not a link to a mailing list, message or thread")

    list_name = list_name.title().replace("Sig", "SIG")
    return list_name, url_type


def _pretty_thread(text: nodes.Text) -> nodes.Text:
    try:
        list_name, url_type = _process_list_url(str(text))
    except ValueError:
        return text

    return nodes.Text(f"{list_name} {url_type}")
