from __future__ import absolute_import

from six import string_types
import json
import decimal
import datetime

from plotly.io._utils import validate_coerce_fig_to_dict, validate_coerce_output_type
from _plotly_utils.optional_imports import get_module
from _plotly_utils.basevalidators import ImageUriValidator


# Orca configuration class
# ------------------------
class JsonConfig(object):
    _valid_engines = ("legacy", "json", "orjson", "auto")

    def __init__(self):
        self._default_engine = "auto"

    @property
    def default_engine(self):
        return self._default_engine

    @default_engine.setter
    def default_engine(self, val):
        if val not in JsonConfig._valid_engines:
            raise ValueError(
                "Supported JSON engines include {valid}\n"
                "    Received {val}".format(valid=JsonConfig._valid_engines, val=val)
            )

        if val == "orjson":
            self.validate_orjson()

        self._default_engine = val

    @classmethod
    def validate_orjson(cls):
        orjson = get_module("orjson")
        if orjson is None:
            raise ValueError("The orjson engine requires the orjson package")


config = JsonConfig()


def coerce_to_strict(const):
    """
    This is used to ultimately *encode* into strict JSON, see `encode`

    """
    # before python 2.7, 'true', 'false', 'null', were include here.
    if const in ("Infinity", "-Infinity", "NaN"):
        return None
    else:
        return const


def time_engine(engine, plotly_object):
    import time
    # time in seconds
    t_total = 0
    n_total = 0

    # Call function for at least total of 2 seconds and at least 10 times
    n_min = 10
    t_min = 1

    while t_total < t_min or n_total < n_min:
        t0 = time.perf_counter()
        _to_json_plotly(plotly_object, engine=engine)
        t1 = time.perf_counter()
        n_total += 1
        t_total += (t1 - t0)

    # return time in ms
    return 1000 * t_total / n_total


def to_json_plotly(plotly_object, pretty=False, engine=None):
    if engine is not None:
        return _to_json_plotly(plotly_object, pretty=pretty , engine=engine)

    # instrucment _to_json_plotly by running it with all 3 engines and comparing results
    # before returnin

    import timeit
    from IPython import get_ipython
    ipython = get_ipython()
    orjson = get_module("orjson", should_load=True)
    results = {}
    timing = {}
    result_str = None
    for engine in ["json", "orjson", "legacy"]:
        if orjson is None and engine == "orjson":
            continue

        result_str = _to_json_plotly(plotly_object, pretty=pretty, engine=engine)
        results[engine] = from_json_plotly(result_str, engine=engine)
        timing[engine] = time_engine(engine, plotly_object)

    # Check matches
    if results["legacy"] != results["json"]:
        raise ValueError(
            """
{legacy}

{json}""".format(
                legacy=results["legacy"], json=results["json"]
            )
        )

    if "orjson" in results:
        if results["json"] != results["orjson"]:
            raise ValueError(
                """
    {json}
    
    {orjson}""".format(
                    json=results["json"], orjson=results["orjson"]
                )
            )

    # write timing
    import uuid
    import pickle
    import os
    uid = str(uuid.uuid4())
    with open("json_timing.csv".format(engine), "at") as f:
        f.write("{}, {}, {}, {}, {}\n".format(
            timing["legacy"], timing["json"], timing["orjson"], len(result_str), uid)
        )
    os.makedirs("json_object", exist_ok=True)
    with open("json_object/{uid}.pkl".format(uid=uid), "wb") as f:
        pickle.dump(plotly_object, f)

    return result_str


def _to_json_plotly(plotly_object, pretty=False, engine=None):
    """
    Convert a plotly/Dash object to a JSON string representation

    Parameters
    ----------
    plotly_object:
        A plotly/Dash object represented as a dict, graph_object, or Dash component

    pretty: bool (default False)
        True if JSON representation should be pretty-printed, False if
        representation should be as compact as possible.

    engine: str (default None)
        The JSON encoding engine to use. One of:
          - "json" for an engine based on the built-in Python json module
          - "orjson" for a faster engine that requires the orjson package
          - "legacy" for the legacy JSON engine.
          - "auto" for the "orjson" engine if available, otherwise "json"
        If not specified, the default engine is set to the current value of
        plotly.io.json.config.default_engine.

    Returns
    -------
    str
        Representation of input object as a JSON string

    See Also
    --------
    to_json : Convert a plotly Figure to JSON with validation
    """
    orjson = get_module("orjson", should_load=True)

    # Determine json engine
    if engine is None:
        engine = config.default_engine

    if engine == "auto":
        if orjson is not None:
            engine = "orjson"
        else:
            engine = "json"
    elif engine not in ["orjson", "json", "legacy"]:
        raise ValueError("Invalid json engine: %s" % engine)

    modules = {
        "sage_all": get_module("sage.all", should_load=False),
        "np": get_module("numpy", should_load=False),
        "pd": get_module("pandas", should_load=False),
        "image": get_module("PIL.Image", should_load=False),
    }

    # Dump to a JSON string and return
    # --------------------------------
    if engine in ("json", "legacy"):
        opts = {"sort_keys": True}
        if pretty:
            opts["indent"] = 2
        else:
            # Remove all whitespace
            opts["separators"] = (",", ":")

        if engine == "json":
            cleaned = clean_to_json_compatible(
                plotly_object,
                numpy_allowed=False,
                datetime_allowed=False,
                modules=modules,
            )
            encoded_o = json.dumps(cleaned, **opts)

            if not ("NaN" in encoded_o or "Infinity" in encoded_o):
                return encoded_o

            # now:
            #    1. `loads` to switch Infinity, -Infinity, NaN to None
            #    2. `dumps` again so you get 'null' instead of extended JSON
            try:
                new_o = json.loads(encoded_o, parse_constant=coerce_to_strict)
            except ValueError:
                # invalid separators will fail here. raise a helpful exception
                raise ValueError(
                    "Encoding into strict JSON failed. Did you set the separators "
                    "valid JSON separators?"
                )
            else:
                return json.dumps(new_o, **opts)
        else:
            from _plotly_utils.utils import PlotlyJSONEncoder

            return json.dumps(plotly_object, cls=PlotlyJSONEncoder, **opts)
    elif engine == "orjson":
        JsonConfig.validate_orjson()
        opts = orjson.OPT_SORT_KEYS | orjson.OPT_SERIALIZE_NUMPY

        if pretty:
            opts |= orjson.OPT_INDENT_2

        # Plotly
        try:
            plotly_object = plotly_object.to_plotly_json()
        except AttributeError:
            pass

        # Try without cleaning
        try:
            return orjson.dumps(plotly_object, option=opts).decode("utf8")
        except TypeError:
            pass

        cleaned = clean_to_json_compatible(
            plotly_object, numpy_allowed=True, datetime_allowed=True, modules=modules,
        )
        return orjson.dumps(cleaned, option=opts).decode("utf8")


def to_json(fig, validate=True, pretty=False, remove_uids=True, engine=None):
    """
    Convert a figure to a JSON string representation

    Parameters
    ----------
    fig:
        Figure object or dict representing a figure

    validate: bool (default True)
        True if the figure should be validated before being converted to
        JSON, False otherwise.

    pretty: bool (default False)
        True if JSON representation should be pretty-printed, False if
        representation should be as compact as possible.

    remove_uids: bool (default True)
        True if trace UIDs should be omitted from the JSON representation

    engine: str (default None)
        The JSON encoding engine to use. One of:
          - "json" for an engine based on the built-in Python json module
          - "orjson" for a faster engine that requires the orjson package
          - "legacy" for the legacy JSON engine.
          - "auto" for the "orjson" engine if available, otherwise "json"
        If not specified, the default engine is set to the current value of
        plotly.io.json.config.default_engine.

    Returns
    -------
    str
        Representation of figure as a JSON string

    See Also
    --------
    to_json_plotly : Convert an arbitrary plotly graph_object or Dash component to JSON
    """
    # Validate figure
    # ---------------
    fig_dict = validate_coerce_fig_to_dict(fig, validate)

    # Remove trace uid
    # ----------------
    if remove_uids:
        for trace in fig_dict.get("data", []):
            trace.pop("uid", None)

    return to_json_plotly(fig_dict, pretty=pretty, engine=engine)


def write_json(fig, file, validate=True, pretty=False, remove_uids=True, engine=None):
    """
    Convert a figure to JSON and write it to a file or writeable
    object

    Parameters
    ----------
    fig:
        Figure object or dict representing a figure

    file: str or writeable
        A string representing a local file path or a writeable object
        (e.g. an open file descriptor)

    pretty: bool (default False)
        True if JSON representation should be pretty-printed, False if
        representation should be as compact as possible.

    remove_uids: bool (default True)
        True if trace UIDs should be omitted from the JSON representation

    engine: str (default None)
        The JSON encoding engine to use. One of:
          - "json" for an engine based on the built-in Python json module
          - "orjson" for a faster engine that requires the orjson package
          - "legacy" for the legacy JSON engine.
          - "auto" for the "orjson" engine if available, otherwise "json"
        If not specified, the default engine is set to the current value of
        plotly.io.json.config.default_engine.
    Returns
    -------
    None
    """

    # Get JSON string
    # ---------------
    # Pass through validate argument and let to_json handle validation logic
    json_str = to_json(
        fig, validate=validate, pretty=pretty, remove_uids=remove_uids, engine=engine
    )

    # Check if file is a string
    # -------------------------
    file_is_str = isinstance(file, string_types)

    # Open file
    # ---------
    if file_is_str:
        with open(file, "w") as f:
            f.write(json_str)
    else:
        file.write(json_str)


def from_json_plotly(value, engine=None):
    """
    Parse JSON string using the specified JSON engine

    Parameters
    ----------
    value: str or bytes
        A JSON string or bytes object

    engine: str (default None)
        The JSON decoding engine to use. One of:
          - if "json" or "legacy", parse JSON using built in json module
          - if "orjson", parse using the faster orjson module, requires the orjson
            package
          - if "auto" use orjson module if available, otherwise use the json module

        If not specified, the default engine is set to the current value of
        plotly.io.json.config.default_engine.

    Returns
    -------
    dict

    See Also
    --------
    from_json_plotly : Parse JSON with plotly conventions into a dict
    """
    orjson = get_module("orjson", should_load=True)

    # Validate value
    # --------------
    if not isinstance(value, (string_types, bytes)):
        raise ValueError(
            """
from_json_plotly requires a string or bytes argument but received value of type {typ}
    Received value: {value}""".format(
                typ=type(value), value=value
            )
        )

    # Determine json engine
    if engine is None:
        engine = config.default_engine

    if engine == "auto":
        if orjson is not None:
            engine = "orjson"
        else:
            engine = "json"
    elif engine not in ["orjson", "json", "legacy"]:
        raise ValueError("Invalid json engine: %s" % engine)

    if engine == "orjson":
        JsonConfig.validate_orjson()
        # orjson handles bytes input natively
        value_dict = orjson.loads(value)
    else:
        # decode bytes to str for built-in json module
        if isinstance(value, bytes):
            value = value.decode("utf-8")
        value_dict = json.loads(value)

    return value_dict


def from_json(value, output_type="Figure", skip_invalid=False, engine=None):
    """
    Construct a figure from a JSON string

    Parameters
    ----------
    value: str or bytes
        String or bytes object containing the JSON representation of a figure

    output_type: type or str (default 'Figure')
        The output figure type or type name.
        One of:  graph_objs.Figure, 'Figure', graph_objs.FigureWidget, 'FigureWidget'

    skip_invalid: bool (default False)
        False if invalid figure properties should result in an exception.
        True if invalid figure properties should be silently ignored.

    engine: str (default None)
        The JSON decoding engine to use. One of:
          - if "json" or "legacy", parse JSON using built in json module
          - if "orjson", parse using the faster orjson module, requires the orjson
            package
          - if "auto" use orjson module if available, otherwise use the json module

        If not specified, the default engine is set to the current value of
        plotly.io.json.config.default_engine.

    Raises
    ------
    ValueError
        if value is not a string, or if skip_invalid=False and value contains
        invalid figure properties

    Returns
    -------
    Figure or FigureWidget
    """

    # Decode JSON
    # -----------
    fig_dict = from_json_plotly(value, engine=engine)

    # Validate coerce output type
    # ---------------------------
    cls = validate_coerce_output_type(output_type)

    # Create and return figure
    # ------------------------
    fig = cls(fig_dict, skip_invalid=skip_invalid)
    return fig


def read_json(file, output_type="Figure", skip_invalid=False, engine=None):
    """
    Construct a figure from the JSON contents of a local file or readable
    Python object

    Parameters
    ----------
    file: str or readable
       A string containing the path to a local file or a read-able Python
       object (e.g. an open file descriptor)

    output_type: type or str (default 'Figure')
        The output figure type or type name.
        One of:  graph_objs.Figure, 'Figure', graph_objs.FigureWidget, 'FigureWidget'

    skip_invalid: bool (default False)
        False if invalid figure properties should result in an exception.
        True if invalid figure properties should be silently ignored.

    engine: str (default None)
        The JSON decoding engine to use. One of:
          - if "json" or "legacy", parse JSON using built in json module
          - if "orjson", parse using the faster orjson module, requires the orjson
            package
          - if "auto" use orjson module if available, otherwise use the json module

        If not specified, the default engine is set to the current value of
        plotly.io.json.config.default_engine.

    Returns
    -------
    Figure or FigureWidget
    """

    # Check if file is a string
    # -------------------------
    # If it's a string we assume it's a local file path. If it's not a string
    # then we assume it's a read-able Python object
    file_is_str = isinstance(file, string_types)

    # Read file contents into JSON string
    # -----------------------------------
    if file_is_str:
        with open(file, "r") as f:
            json_str = f.read()
    else:
        json_str = file.read()

    # Construct and return figure
    # ---------------------------
    return from_json(
        json_str, skip_invalid=skip_invalid, output_type=output_type, engine=engine
    )


def clean_to_json_compatible(obj, **kwargs):
    # Try handling value as a scalar value that we have a conversion for.
    # Return immediately if we know we've hit a primitive value

    # Bail out fast for simple scalar types
    if isinstance(obj, (int, float, string_types)):
        return obj

    # Plotly
    try:
        obj = obj.to_plotly_json()
    except AttributeError:
        pass

    # And simple lists
    if isinstance(obj, (list, tuple)):
        # Must process list recursively even though it may be slow
        return [clean_to_json_compatible(v, **kwargs) for v in obj]
    # Recurse into lists and dictionaries
    if isinstance(obj, dict):
        return {k: clean_to_json_compatible(v, **kwargs) for k, v in obj.items()}

    # unpack kwargs
    numpy_allowed = kwargs.get("numpy_allowed", False)
    datetime_allowed = kwargs.get("datetime_allowed", False)

    modules = kwargs.get("modules", {})
    sage_all = modules["sage_all"]
    np = modules["np"]
    pd = modules["pd"]
    image = modules["image"]

    # Sage
    if sage_all is not None:
        if obj in sage_all.RR:
            return float(obj)
        elif obj in sage_all.ZZ:
            return int(obj)

    # numpy
    if np is not None:
        if obj is np.ma.core.masked:
            return float("nan")
        elif isinstance(obj, np.ndarray):
            if numpy_allowed and obj.dtype.kind in ("b", "i", "u", "f"):
                return np.ascontiguousarray(obj)
            elif obj.dtype.kind == "M":
                # datetime64 array
                return np.datetime_as_string(obj).tolist()
            elif obj.dtype.kind == "U":
                return obj.tolist()
            elif obj.dtype.kind == "O":
                # Treat object array as plain list, allow recursive processing below
                obj = obj.tolist()
        elif isinstance(obj, np.datetime64):
            return str(obj)

    # pandas
    if pd is not None:
        if obj is pd.NaT:
            return None
        elif isinstance(obj, (pd.Series, pd.DatetimeIndex)):
            if numpy_allowed and obj.dtype.kind in ("b", "i", "u", "f"):
                return np.ascontiguousarray(obj.values)
            elif obj.dtype.kind == "M":
                if isinstance(obj, pd.Series):
                    dt_values = obj.dt.to_pydatetime().tolist()
                else:  # DatetimeIndex
                    dt_values = obj.to_pydatetime().tolist()

                if not datetime_allowed:
                    # Note: We don't need to handle dropping timezones here because
                    # numpy's datetime64 doesn't support them and pandas's tz_localize
                    # above drops them.
                    for i in range(len(dt_values)):
                        dt_values[i] = dt_values[i].isoformat()

                return dt_values

    # datetime and date
    try:
        # Need to drop timezone for scalar datetimes. Don't need to convert
        # to string since engine can do that
        obj = obj.to_pydatetime()
    except (TypeError, AttributeError):
        pass

    if not datetime_allowed:
        try:
            return obj.isoformat()
        except (TypeError, AttributeError):
            pass
    elif isinstance(obj, datetime.datetime):
        return obj

    # Try .tolist() convertible, do not recurse inside
    try:
        return obj.tolist()
    except AttributeError:
        pass

    # Do best we can with decimal
    if isinstance(obj, decimal.Decimal):
        return float(obj)

    # PIL
    if image is not None and isinstance(obj, image.Image):
        return ImageUriValidator.pil_image_to_uri(obj)

    if isinstance(obj, (list, tuple)) and obj:
        # Must process list recursively even though it may be slow
        return [clean_to_json_compatible(v, **kwargs) for v in obj]

    return obj
