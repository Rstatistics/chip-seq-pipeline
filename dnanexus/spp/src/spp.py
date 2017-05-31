#!/usr/bin/env python2
# spp 0.0.1
# Generated by dx-app-wizard.
#
# Basic execution pattern: Your app will run on a single machine from
# beginning to end.
#
# See https://wiki.dnanexus.com/Developer-Portal for documentation and
# tutorials on how to modify this file.
#
# DNAnexus Python Bindings (dxpy) documentation:
#   http://autodoc.dnanexus.com/bindings/python/current/

import subprocess
import shlex
import filecmp
from multiprocessing import cpu_count
import dxpy
import common
import logging

logger = logging.getLogger(__name__)
logger.addHandler(dxpy.DXLogHandler())
logger.propagate = False
logger.setLevel(logging.INFO)

SPP_VERSION_MAP = {
    "1.10.1": "/phantompeakqualtools/spp_1.10.1.tar.gz",
    "1.14":   "/phantompeakqualtools/spp-1.14.tar.gz"
}


@dxpy.entry_point('main')
def main(experiment, control, xcor_scores_input, npeaks, nodups, bigbed,
         chrom_sizes, spp_version, as_file=None, prefix=None,
         fragment_length=None):

    # The following line(s) initialize your data object inputs on the platform
    # into dxpy.DXDataObject instances that you can start using immediately.

    experiment_file = dxpy.DXFile(experiment)
    control_file = dxpy.DXFile(control)
    xcor_scores_input_file = dxpy.DXFile(xcor_scores_input)
    chrom_sizes_file = dxpy.DXFile(chrom_sizes)
    chrom_sizes_filename = chrom_sizes_file.name
    dxpy.download_dxfile(chrom_sizes_file.get_id(), chrom_sizes_filename)
    if bigbed:
        as_file_file = dxpy.DXFile(as_file)
        as_file_filename = as_file_file.name
        dxpy.download_dxfile(as_file_file.get_id(), as_file_filename)

    # The following line(s) download your file inputs to the local file system
    # using variable names for the filenames.

    experiment_filename = experiment_file.name
    dxpy.download_dxfile(experiment_file.get_id(), experiment_filename)

    control_filename = control_file.name
    dxpy.download_dxfile(control_file.get_id(), control_filename)

    xcor_scores_input_filename = xcor_scores_input_file.name
    dxpy.download_dxfile(
        xcor_scores_input_file.get_id(), xcor_scores_input_filename)

    if not prefix:
        output_filename_prefix = \
            experiment_filename.rstrip('.gz').rstrip('.tagAlign')
    else:
        output_filename_prefix = prefix
    peaks_filename = output_filename_prefix + '.regionPeak'
    # spp adds .gz, so this is the file name that's actually created
    final_peaks_filename = peaks_filename + '.gz'
    xcor_plot_filename = output_filename_prefix + '.pdf'
    xcor_scores_filename = output_filename_prefix + '.ccscores'

    logger.info(subprocess.check_output(
        'ls -l', shell=True, stderr=subprocess.STDOUT))

    # third column in the cross-correlation scores input file
    # if fragment_length is provided, use that. Else read
    # fragment length from xcor file
    if fragment_length:
        fraglen = fragment_length
        logger.info("User given fragment length %s" % fraglen)
    else:
        fraglen_column = 3
        with open(xcor_scores_input_filename, 'r') as f:
            line = f.readline()
            fraglen = line.split('\t')[fraglen_column-1]
            logger.info("Read fragment length: %s" % (fraglen))

    spp_tarball = SPP_VERSION_MAP.get(spp_version)
    assert spp_tarball, "spp version %s is not supported" % (spp_version)
    if nodups:
        run_spp = '/phantompeakqualtools/run_spp_nodups.R'
    else:
        run_spp = '/phantompeakqualtools/run_spp.R'
    # install spp
    subprocess.check_output(shlex.split('R CMD INSTALL %s' % (spp_tarball)))
    spp_command = (
        "Rscript %s -p=%d -c=%s -i=%s -npeak=%d -speak=%s -savr=%s -savp=%s -rf -out=%s"
        % (run_spp, cpu_count(), experiment_filename, control_filename, npeaks,
           fraglen, peaks_filename, xcor_plot_filename,
           xcor_scores_filename))
    logger.info(spp_command)
    subprocess.check_call(shlex.split(spp_command))

    # when one of the peak coordinates are an exact multiple of 10, spp (R)
    # outputs the coordinate in scientific notation
    # this changes any such coodinates to decimal notation
    # this assumes 10-column output and that the 2nd and 3rd columns are
    # coordinates
    # the ($2>0)?$2:0) is needed because spp sometimes calls peaks with a
    # negative start coordinate (particularly chrM) and will cause slopBed
    # to halt at that line, truncating the output of the pipe
    # slopBed adjusts feature end coordinates that go off the end of the
    # chromosome
    # bedClip removes any features that are still not within the boundaries of
    # the chromosome

    fix_coordinate_peaks_filename = \
        output_filename_prefix + '.fixcoord.regionPeak'

    out, err = common.run_pipe([
        "gzip -dc %s" % (final_peaks_filename),
        "tee %s" % (peaks_filename),
        r"""awk 'BEGIN{OFS="\t"}{print $1,sprintf("%i",($2>0)?$2:0),sprintf("%i",$3),$4,$5,$6,$7,$8,$9,$10}'""",
        'slopBed -i stdin -g %s -b 0' % (chrom_sizes_filename),
        'bedClip stdin %s %s' % (chrom_sizes_filename, fix_coordinate_peaks_filename)
    ])

    # These lines transfer the peaks files to the temporary workspace for
    # debugging later
    # Only at the end are the final files uploaded that will be returned from
    # the applet
    dxpy.upload_local_file(peaks_filename)
    dxpy.upload_local_file(fix_coordinate_peaks_filename)

    n_spp_peaks = common.count_lines(peaks_filename)
    logger.info("%s peaks called by spp" % (n_spp_peaks))
    logger.info(
        "%s of those peaks removed due to bad coordinates"
        % (n_spp_peaks - common.count_lines(fix_coordinate_peaks_filename)))
    print("First 50 peaks")
    subprocess.check_output(
        'head -50 %s' % (fix_coordinate_peaks_filename),
        shell=True)

    if bigbed:
        peaks_bb_filename = \
            common.bed2bb(fix_coordinate_peaks_filename, chrom_sizes_filename, as_file_filename)
        if peaks_bb_filename:
            peaks_bb = dxpy.upload_local_file(peaks_bb_filename)

    if not filecmp.cmp(peaks_filename,fix_coordinate_peaks_filename):
        logger.info("Returning peaks with fixed coordinates")
        subprocess.check_call(shlex.split('gzip -n %s' % (fix_coordinate_peaks_filename)))
        final_peaks_filename = fix_coordinate_peaks_filename + '.gz'

    subprocess.check_call('ls -l', shell=True)
    # print subprocess.check_output('head %s' %(final_peaks_filename), shell=True, stderr=subprocess.STDOUT)
    # print subprocess.check_output('head %s' %(xcor_scores_filename), shell=True, stderr=subprocess.STDOUT)

    peaks = dxpy.upload_local_file(final_peaks_filename)
    xcor_plot = dxpy.upload_local_file(xcor_plot_filename)
    xcor_scores = dxpy.upload_local_file(xcor_scores_filename)

    output = {}
    output["peaks"] = dxpy.dxlink(peaks)
    output["xcor_plot"] = dxpy.dxlink(xcor_plot)
    output["xcor_scores"] = dxpy.dxlink(xcor_scores)
    if bigbed and peaks_bb_filename:
        output["peaks_bb"] = dxpy.dxlink(peaks_bb)

    return output

dxpy.run()
